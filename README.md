[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

![Android app screenshot](https://i.imgur.com/xxmUkCp.jpg)

## Requirements

 - Android Studio
 - Android SDK
 - Python 3.7+ (additional libraries: janus)
 - Tensorflow 2.0
 - Gradle
 - NodeJS + npm

## Build/Run Instructions

### Models

To generate the models, run:

```bash
python generate_models.py
```

Then, create the folder `sdcard/collaborative-intelligence` on the device, and
copy `models.json` and the generated `*.tflite` models and into the folder:

```bash
adb shell mkdir "sdcard/collaborative-intelligence/"
adb push models.json "/sdcard/collaborative-intelligence/"
adb push models/**/*.tflite "/sdcard/collaborative-intelligence/"
```

### Server

Please ensure that the ports 5678 and 5680 are open on the server.

To start up the server, run:

```bash
python server.py
```

### Android Application

In
[`NetworkAdapter.kt`](android/app/src/main/java/com/sicariusnoctis/collaborativeintelligence/NetworkAdapter.kt),
set `HOSTNAME` to the desired server host. (For LAN connections, this should
look something similar to `"192.168.100.175"`. You can determine this by
running `ip addr` on your server.)

To build and install on your android device, simply open the
[`android`](android) directory in Android Studio and click "Run".

**NOTE:** Please ensure that you enable the listed app permissions on your
Android device. (To do this, find the app in your home screen, then long-press
the app icon, choose "App info", choose "Permissions", then enable the
sliders.)

*Alternatively,* you may run the gradle build script instead:

```bash
cd android
./gradlew build
./gradlew installDebug
```

To install a release build instead, you need to create a temporary certificate
to sign the APK with:

```bash
cd android
./gradlew build
./gradlew assembleRelease

keytool -genkey -v -keystore my-release-key.keystore -alias alias_name -keyalg RSA -keysize 2048 -validity 10000
jarsigner -verbose -sigalg SHA1withRSA -digestalg SHA1 -keystore my-release-key.keystore "app/build/outputs/apk/release/app-release-unsigned.apk" alias_name
adb install ./app/build/outputs/apk/release/app-release-unsigned.apk
```

### Server Monitor

The server monitor allows monitoring of the server via a GUI client.

By default, the server monitor connects to a server running on `"localhost"`,
but you may change the following line in [`main.ts`](server-monitor/src/main.ts):

```typescript
const HOSTNAME: string = "localhost";
```

To install the required packages and run:

```bash
npm install
npm run start
```
