# Insights Mobile

Expo Go TypeScript shell for the Django site in `current_website/`.

## What this app does

- Wraps the Django site in `react-native-webview`
- Adds a native header, bottom navigation, and drawer around the web content
- Uses Expo-native APIs for camera and notification permissions
- Keeps the Django templates as the primary UI/content layer

## Local setup

1. Start the Django server from `current_website/`.
2. For a phone on the same network, create a `.env` file in `mobile_app/` and set:

```env
EXPO_PUBLIC_INSIGHTS_SITE_URL=http://YOUR-LAN-IP:8000
EXPO_PUBLIC_EXPO_PROJECT_ID=your-expo-project-id
```

`EXPO_PUBLIC_EXPO_PROJECT_ID` is required for Expo push token registration in current Expo SDKs. Without it, the app can request permission but the `Enable Notifications` action cannot finish push setup.

3. If you are using the Android emulator, the app defaults to `http://10.0.2.2:8000`.
4. Install dependencies with `npm install`.
5. Run `npm start`.
6. Open Expo Go on Android or iPhone and connect to the running Expo session.

## Useful commands

```bash
npm start
npm run start:tunnel
npm run android
npm run ios
npm run web
npm run typecheck
```

## Files to know

- `App.tsx`: main Expo shell with native chrome and the WebView
- `src/config.ts`: route list and base URL resolution
- `.env.example`: sample environment variable for Django host configuration

## Notes

- Expo Go is the intended workflow for fast Android and iPhone iteration from one codebase.
- `npm run ios` still depends on Expo/iOS tooling availability, but Expo Go on a physical iPhone works from Windows on the same network.
- The camera action uses Expo Image Picker's native camera flow.
- Notification permission status is tracked in the shell; full production push setup still requires Expo credentials and app-specific configuration.