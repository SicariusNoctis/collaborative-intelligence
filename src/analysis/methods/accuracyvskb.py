import textwrap
from collections import defaultdict
from os import path
from typing import Callable, Dict, Iterator, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import tensorflow as tf
import tensorflow_datasets as tfds
from tensorflow import keras

from src.analysis import dataset as ds
from src.analysis import plot
from src.analysis.utils import (
    basename_of,
    predict_dataset,
    predict_dataset_into_dataset,
    title_of,
)
from src.lib.layouts import TensorLayout
from src.lib.postencode import JpegPostencoder, Postencoder
from src.lib.predecode import JpegPredecoder, Predecoder

BYTES_PER_KB = 1000


# TODO loop postencoders...?
def analyze_accuracyvskb_layer(
    model_name: str,
    model: keras.Model,
    model_client: keras.Model,
    model_server: keras.Model,
    layer_name: str,
    layer_i: int,
    layer_n: int,
    quant: Callable[[np.ndarray], np.ndarray],
    dequant: Callable[[np.ndarray], np.ndarray],
    batch_size: int,
    subdir: str = "",
):
    if len(model_client.output_shape) != 4:
        return

    title = title_of(model_name, layer_name, layer_i, layer_n)
    basename = basename_of(model_name, layer_name, layer_i, layer_n)
    basedir = "img/accuracyvskb"
    shareddir = path.join(basedir, subdir)
    filename_server = path.join(basedir, f"{model_name}-server.csv")
    filename_shared = path.join(shareddir, f"{basename}-shared.csv")

    try:
        data_server = pd.read_csv(filename_server)
    except FileNotFoundError:
        data_server = _evaluate_accuracies_server_kb(model, batch_size)
        data_server.to_csv(filename_server)
        print("Analyzed server accuracy vs KB")

    try:
        data_shared = pd.read_csv(filename_shared)
    except FileNotFoundError:
        data_shared = _evaluate_accuracies_shared_kb(
            model_client, model_server, quant, dequant, batch_size
        )
        data_shared.to_csv(filename_shared)
        print("Analyzed shared accuracy vs KB")

    fig = _plot_accuracy_vs_kb(title, data_server, data_shared)
    plot.save(fig, path.join(shareddir, f"{basename}.png"))
    print("Analyzed accuracy vs KB")


def _evaluate_accuracy_kb(
    model: keras.Model, kb: int, batch_size: int
) -> np.ndarray:
    dataset = ds.dataset_kb(kb)
    predictions = predict_dataset(model, dataset.batch(batch_size))
    labels = np.array(list(tfds.as_numpy(dataset.map(_second))))
    accuracies = _categorical_top1_accuracy(labels, predictions)
    kbs = np.ones_like(accuracies) * kb
    return np.vstack((kbs, accuracies))


def _evaluate_accuracies_server_kb(
    model: keras.Model, batch_size: int,
) -> pd.DataFrame:
    accuracies_server = [
        _evaluate_accuracy_kb(model, kb, batch_size) for kb in range(1, 31)
    ]
    accuracies_server = np.concatenate(accuracies_server, axis=1)
    kbs_server = accuracies_server[0] / 1.024
    acc_server = accuracies_server[1]
    return pd.DataFrame({"kbs": kbs_server, "acc": acc_server})


def _evaluate_accuracies_shared_kb(
    model_client: keras.Model,
    model_server: keras.Model,
    quant: Callable[[np.ndarray], np.ndarray],
    dequant: Callable[[np.ndarray], np.ndarray],
    batch_size: int,
) -> pd.DataFrame:

    # TODO also, for JPEG2000, rate control rather than LUT for required quality

    dataset = ds.dataset()
    dataset_client = predict_dataset_into_dataset(model_client, dataset)
    dataset_recv = _generate_jpeg_dataset(
        dataset_client, model_server.input_shape, quant, dequant
    )

    byte_sizes = []
    accuracies = []
    labels = []

    for xs, ls, bs in tfds.as_numpy(dataset_recv.batch(batch_size)):
        xs = model_server.predict_on_batch(xs)
        accs = _categorical_top1_accuracy(xs, ls)
        accuracies.extend(accs)
        labels.extend(ls)
        byte_sizes.extend(bs)
        print(f"n={len(accuracies)}...")

    kbs = byte_sizes / 1024
    df = pd.DataFrame(
        # {"byte_size": byte_sizes, "acc": accuracies, "label": labels}
        {"kbs": kbs, "acc": accuracies, "label": labels}
    )

    # TODO Shouldn't this be moved... outside...?
    bins = np.linspace(0.9, 30.1, num=5 * 29 + 2)
    mids = 0.5 * (bins[:-1] + bins[1:])
    df.sort_values("kbs", inplace=True)
    df = df[(bins[0] < df["kbs"]) & (df["kbs"] < bins[-1])]
    df["kbs"] = mids[np.digitize(df["kbs"], bins)]

    return df


def _generate_jpeg_dataset(
    dataset: tf.data.Dataset,
    shape: tuple,
    quant: Callable[[np.ndarray], np.ndarray],
    dequant: Callable[[np.ndarray], np.ndarray],
) -> tf.data.Dataset:
    """Dataset of reconstructed tensors from various compressed sizes"""

    def map_func(client_tensor: np.ndarray, label: int):
        def _func(x: np.ndarray):
            _generate_jpeg_tensors(x, quant, dequant)

        xs, bs = tf.py_function(
            _func, inp=[client_tensor], Tout=[tf.float32, tf.int64]
        )
        ls = tf.ones_like(bs) * label
        print(xs, ls, bs)
        return xs, ls, bs

    return dataset.map(map_func).unbatch()

    # def gen():
    #     for client_tensor, label in tfds.as_numpy(dataset):
    #         for x, b in _generate_jpeg_tensors(client_tensor, quant, dequant):
    #             yield x, label, b
    #
    # return tf.data.Dataset.from_generator(
    #     gen,
    #     (tf.float32, tf.int64, tf.int64),
    #     (tf.TensorShape(shape), tf.TensorShape([]), tf.TensorShape([])),
    # )


def _generate_jpeg_tensors(
    client_tensor: np.ndarray,
    quant: Callable[[np.ndarray], np.ndarray],
    dequant: Callable[[np.ndarray], np.ndarray],
) -> Tuple[List[np.ndarray], List[int]]:
    """Returns reconstructed tensors from various compressed sizes"""
    tensor_layout = TensorLayout.from_tensor(client_tensor, "hwc")
    tiled_layout = JpegPostencoder(tensor_layout).tiled_layout
    d = {}
    xs = []
    bs = []

    for quality in range(1, 101):
        postencoder = JpegPostencoder(tensor_layout, quality=quality)
        x = client_tensor
        x = quant(x)
        x = postencoder.run(x)
        b = len(x)
        d[b] = x, quality

    for b, (x, quality) in d.items():
        predecoder = JpegPredecoder(tiled_layout, tensor_layout)
        x = predecoder.run(x)
        x = dequant(x)
        xs.append(x)
        bs.append(b)

    return xs, bs


# def _generate_jpeg_dataset(
#     dataset: tf.data.Dataset,
#     shape: tuple,
#     quant: Callable[[np.ndarray], np.ndarray],
#     dequant: Callable[[np.ndarray], np.ndarray],
# ) -> tf.data.Dataset:
#     """Dataset of reconstructed tensors from various compressed sizes"""
#
#     def gen():
#         for client_tensor, label in tfds.as_numpy(dataset):
#             for x, b in _generate_jpeg_tensors(client_tensor, quant, dequant):
#                 yield x, label, b
#
#     return tf.data.Dataset.from_generator(
#         gen,
#         (tf.float32, tf.int64, tf.int64),
#         (tf.TensorShape(shape), tf.TensorShape([]), tf.TensorShape([])),
#     )
#
#
# def _generate_jpeg_tensors(
#     client_tensor: np.ndarray,
#     quant: Callable[[np.ndarray], np.ndarray],
#     dequant: Callable[[np.ndarray], np.ndarray],
# ) -> Iterator[Tuple[np.ndarray, int]]:
#     """Yields reconstructed tensors from various compressed sizes"""
#     tensor_layout = TensorLayout.from_tensor(client_tensor, "hwc")
#     tiled_layout = JpegPostencoder(tensor_layout).tiled_layout
#     d = {}
#
#     for quality in range(1, 101):
#         postencoder = JpegPostencoder(tensor_layout, quality=quality)
#         x = client_tensor
#         x = quant(x)
#         x = postencoder.run(x)
#         b = len(x)
#         d[b] = x, quality
#
#     for b, (x, quality) in d.items():
#         predecoder = JpegPredecoder(tiled_layout, tensor_layout)
#         x = predecoder.run(x)
#         x = dequant(x)
#         yield x, b


def _plot_accuracy_vs_kb(
    title: str, data_server: pd.DataFrame, data_shared: pd.DataFrame
):
    fig = plt.figure()
    ax = sns.lineplot(x="kbs", y="acc", data=data_server)
    ax = sns.lineplot(x="kbs", y="acc", data=data_shared)
    ax: plt.Axes = plt.gca()
    ax.legend(
        labels=["server-only inference", "shared inference"],
        loc="lower right",
    )
    ax.set(xlim=(0, 30), ylim=(0, 1))
    ax.set_xlabel("KB/frame")
    ax.set_ylabel("Accuracy")
    ax.set_title(title, fontsize="xx-small")
    return fig


def _categorical_top1_accuracy(
    label: np.ndarray, pred: np.ndarray
) -> np.ndarray:
    return (np.argmax(pred, axis=-1) == label).astype(np.float32)


@tf.function(autograph=False)
def _first(x, _y):
    return x


@tf.function(autograph=False)
def _second(_x, y):
    return y
