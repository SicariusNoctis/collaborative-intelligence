from typing import Tuple

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from scipy import ndimage

import src.analysis.dataset as ds
from src.analysis import plot
from src.analysis.experimentrunner import ExperimentRunner
from src.analysis.utils import tf_disable_eager_execution

tf_disable_eager_execution()

BATCH_SIZE = 64
DATASET_SIZE = 64


def featuremapsequence(
    frames: np.ndarray,
    tensors: np.ndarray,
    preds: np.ndarray,
    diffs: np.ndarray,
    title: str,
    order: str = "hwc",
    *,
    clim: Tuple[int, int] = None,
    clim_diff: Tuple[int, int] = None,
    cmap="viridis",
) -> plt.Figure:
    n = len(frames)
    ncols = 4
    nrows = n
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(10, 10), constrained_layout=True
    )
    fill_value = clim[0] if clim is not None else None

    def plot_ax(ax, img, *, clim=clim, cbar=False):
        im = ax.matshow(img, cmap=cmap)
        ax.set_xticks([])
        ax.set_yticks([])
        if clim is not None:
            im.set_clim(*clim)
        if cbar:
            fig.colorbar(im, ax=ax)

    for i, img in enumerate(frames):
        plot_ax(axes[i, 0], img)

    for i, arr in enumerate(tensors):
        img = plot.featuremap_image(arr, order, fill_value=fill_value)
        plot_ax(axes[i, 1], img)

    for i, arr in enumerate(preds, start=1):
        img = plot.featuremap_image(arr, order, fill_value=fill_value)
        plot_ax(axes[i, 2], img)

    for i, arr in enumerate(diffs, start=1):
        img = plot.featuremap_image(arr, order, fill_value=fill_value)
        plot_ax(axes[i, 3], img, cbar=True, clim=clim_diff)

    axes[0, 2].axis("off")
    axes[0, 3].axis("off")

    # fig.suptitle(title, fontsize="xx-small")
    return fig


def main():
    runner = ExperimentRunner(
        model_name="resnet34",
        layer_name="add_3",
        dataset_size=DATASET_SIZE,
        batch_size=BATCH_SIZE,
    )

    shape = runner.tensor_layout.shape
    dtype = runner.tensor_layout.dtype
    h, w, c = shape

    n = 4
    px = 2
    offset = 0.25
    x_in_per_cl = 224 / w
    dx_inputs = (((np.arange(n) * px) + offset) * x_in_per_cl).astype(np.int64)
    # dx_inputs = ((np.arange(n) * offset + px) * x_in_per_cl).astype(np.int64)
    dx_inputs[0] = 0
    dx_clients = dx_inputs / x_in_per_cl
    dy_clients = np.zeros(n)

    frames = ds.single_sample_image_xtrans(dx_inputs)
    client_tensors = runner.model_client.predict(frames)
    prev = client_tensors[0]
    diffs = np.empty((len(client_tensors) - 1, *shape), dtype=dtype)
    preds = np.empty((len(client_tensors) - 1, *shape), dtype=dtype)
    mses = np.empty(len(client_tensors) - 1)
    psnrs = np.empty(len(client_tensors) - 1)

    for i, curr in enumerate(client_tensors[1:]):
        r = np.max(curr) - np.min(curr)
        yy, xx, cc = np.meshgrid(
            np.arange(h), np.arange(w), np.arange(c), indexing="ij"
        )
        yy = yy + dy_clients[i + 1]
        xx = xx + dx_clients[i + 1]
        mask = (yy < 0) | (yy > h - 1) | (xx < 0) | (xx > w - 1)
        yy = np.clip(yy, 0, h - 1).reshape(-1)
        xx = np.clip(xx, 0, w - 1).reshape(-1)
        cc = cc.reshape(-1)

        pred = ndimage.map_coordinates(prev, [yy, xx, cc], order=3)
        pred = pred.reshape(h, w, -1)
        preds[i] = pred

        diff = curr - pred
        diff[mask] = 0
        diffs[i] = diff

        x = diff[~mask]
        mses[i] = np.mean(x ** 2)
        psnrs[i] = 10 * np.log(r ** 2 / mses[i])

        # preds[mask] = 0

    print(dx_inputs)
    print(dx_clients)
    print(mses)
    print(psnrs)

    def visual_adjust_tensor(t):
        off = t - np.mean(t)
        return np.copysign(np.abs(off) ** 0.5, off) + np.mean(t)

    # Adjust for visual purposes
    client_tensors = visual_adjust_tensor(client_tensors)
    preds = visual_adjust_tensor(preds)
    diffs = np.abs(diffs)

    # Show only k channels
    koff = 0
    k = 4**2
    client_tensors = client_tensors[..., koff:koff + k]
    preds = preds[..., koff:koff + k]
    diffs = diffs[..., koff:koff + k]

    suffix = f"input_translate_{px}px_{offset}plus_order3"
    # fig = featuremapsequence(frames, client_tensors, preds, diffs, title="", clim_diff=(0, client_tensors.max() - client_tensors.min()))
    fig = featuremapsequence(frames, client_tensors, preds, diffs, title="", clim_diff=(0, 3))
    plot.save(
        fig,
        f"img/experiment/{runner.basename}-{suffix}.png",
        bbox_inches="tight",
    )


main()
