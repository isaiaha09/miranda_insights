import { StatusBar } from 'expo-status-bar';
import * as ImagePicker from 'expo-image-picker';
import * as Notifications from 'expo-notifications';
import { Ionicons } from '@expo/vector-icons';
import { type ReactNode, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Animated,
  Dimensions,
  Easing,
  Image,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { WebView } from 'react-native-webview';

import {
  BASE_URL,
  BASE_URL_LABEL,
  BOTTOM_NAV_ROUTES,
  DEFAULT_BASE_URL,
  DRAWER_ROUTES,
  buildRouteUrl,
  getRouteForUrl,
  markMobileAppUrl,
} from './src/config';

const DRAWER_WIDTH = 320;
const SCREEN_WIDTH = Dimensions.get('window').width;
const AUTH_ACCENT_COLOR = '#6797ea';
const WEB_LOADER_MIN_DURATION_MS = 2500;
const MOBILE_LOGIN_PATH = '/mobile-api/login/';
const MOBILE_USERNAME_RECOVERY_PATH = '/mobile-api/recover-username/';
const MOBILE_PASSWORD_RESET_PATH = '/mobile-api/password-reset/';

type NativeScreen = 'landing' | 'login' | 'twoFactor' | 'forgotUsername' | 'forgotPassword' | 'web';
type NativeAppScreen = Exclude<NativeScreen, 'web'>;
type NativeTransitionDirection = 'forward' | 'back';

type MobileApiResponse = {
  ok?: boolean;
  message?: string;
  sessionUrl?: string;
  redirectUrl?: string;
  requiresTwoFactor?: boolean;
  displayName?: string;
  fieldErrors?: Record<string, string[]>;
};

const MOBILE_WEBVIEW_CLEANUP_SCRIPT = `
  (function () {
    function applyMobileCleanup() {
      var selectors = ['.site-header', '.nav-overlay', '.site-footer', 'footer.site-footer', '.pwa-install-banner', '.turnstile-wrap', '.cf-turnstile', 'iframe[src*="challenges.cloudflare.com"]'];

      selectors.forEach(function (selector) {
        document.querySelectorAll(selector).forEach(function (node) {
          node.style.display = 'none';
          node.style.visibility = 'hidden';
          node.style.height = '0';
          node.style.minHeight = '0';
          node.style.overflow = 'hidden';
          node.setAttribute('hidden', 'hidden');
        });
      });

      var style = document.getElementById('insights-mobile-webview-style');
      if (!style) {
        style = document.createElement('style');
        style.id = 'insights-mobile-webview-style';
        style.textContent = '.site-header, .nav-overlay, .site-footer, footer.site-footer, .pwa-install-banner, .turnstile-wrap, .cf-turnstile, iframe[src*="challenges.cloudflare.com"]{display:none !important;visibility:hidden !important;height:0 !important;min-height:0 !important;overflow:hidden !important;} html, body{padding-top:0 !important;overscroll-behavior:none !important;background:#0c111b !important;} .site-main{padding-top:0 !important;}';
        (document.head || document.documentElement).appendChild(style);
      }

      document.documentElement.style.setProperty('--header-height', '0px');
      document.documentElement.style.background = '#0c111b';
      document.documentElement.style.overscrollBehavior = 'none';
      document.cookie = 'insights_mobile_app=1; path=/; SameSite=Lax';

      if (document.body) {
        document.body.style.background = '#0c111b';
        document.body.style.overscrollBehavior = 'none';
      }

      var siteMain = document.querySelector('.site-main');
      if (siteMain) {
        siteMain.style.paddingTop = '0';
      }
    }

    applyMobileCleanup();
    document.addEventListener('DOMContentLoaded', applyMobileCleanup);
    window.addEventListener('load', applyMobileCleanup);
  })();
  true;
`;

export default function App() {
  const webViewRef = useRef<WebView>(null);
  const webLoaderTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const webLoaderStartedAtRef = useRef<number>(0);
  const drawerOffset = useRef(new Animated.Value(-DRAWER_WIDTH)).current;
  const nativeScreenTranslate = useRef(new Animated.Value(0)).current;
  const previousNativeScreenTranslate = useRef(new Animated.Value(0)).current;
  const previousNativeScreenOpacity = useRef(new Animated.Value(1)).current;
  const nativeScreenTransitionRef = useRef<Animated.CompositeAnimation | null>(null);
  const landingDataMotion = useRef(new Animated.Value(0)).current;
  const landingAnimationRef = useRef<Animated.CompositeAnimation | null>(null);
  const [nativeScreen, setNativeScreen] = useState<NativeScreen>('landing');
  const [transitioningFromScreen, setTransitioningFromScreen] = useState<NativeAppScreen | null>(null);
  const [transitioningToScreen, setTransitioningToScreen] = useState<NativeAppScreen | null>(null);
  const [currentUrl, setCurrentUrl] = useState(buildRouteUrl('/'));
  const [currentTitle, setCurrentTitle] = useState('Insights');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pageReady, setPageReady] = useState(false);
  const [showWebLoader, setShowWebLoader] = useState(false);
  const [capturedImageUri, setCapturedImageUri] = useState<string | null>(null);
  const [webError, setWebError] = useState<string | null>(null);
  const [searchSheetOpen, setSearchSheetOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [recoveryEmail, setRecoveryEmail] = useState('');
  const [passwordResetEmail, setPasswordResetEmail] = useState('');
  const [authError, setAuthError] = useState<string | null>(null);
  const [authNotice, setAuthNotice] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const shouldAnimateBrandIcon = nativeScreen === 'landing' || (nativeScreen === 'web' && !pageReady && !webError);
  const activeRoute = getRouteForUrl(currentUrl);
  const searchResults = DRAWER_ROUTES.filter(function (route) {
    const query = searchQuery.trim().toLowerCase();

    if (!query) {
      return true;
    }

    return route.label.toLowerCase().includes(query) || route.path.toLowerCase().includes(query);
  });

  useEffect(() => {
    Animated.timing(drawerOffset, {
      toValue: drawerOpen ? 0 : -DRAWER_WIDTH,
      duration: 220,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [drawerOffset, drawerOpen]);

  useEffect(() => {
    if (!shouldAnimateBrandIcon) {
      landingAnimationRef.current?.stop();
      landingAnimationRef.current = null;
      return;
    }

    landingAnimationRef.current?.stop();
    landingDataMotion.setValue(0);
    landingAnimationRef.current = Animated.loop(
      Animated.sequence([
        Animated.timing(landingDataMotion, {
          toValue: 1,
          duration: 3600,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: false,
        }),
        Animated.timing(landingDataMotion, {
          toValue: 0,
          duration: 3600,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: false,
        }),
      ])
    );

    landingAnimationRef.current.start();

    return () => {
      landingAnimationRef.current?.stop();
    };
  }, [landingDataMotion, shouldAnimateBrandIcon]);

  useEffect(() => {
    return () => {
      if (webLoaderTimeoutRef.current) {
        clearTimeout(webLoaderTimeoutRef.current);
      }
    };
  }, []);

  function clearWebLoaderTimeout() {
    if (webLoaderTimeoutRef.current) {
      clearTimeout(webLoaderTimeoutRef.current);
      webLoaderTimeoutRef.current = null;
    }
  }

  function beginWebLoader() {
    clearWebLoaderTimeout();
    webLoaderStartedAtRef.current = Date.now();
    setPageReady(false);
    setShowWebLoader(true);
  }

  function finishWebLoader() {
    clearWebLoaderTimeout();
    const elapsed = Date.now() - webLoaderStartedAtRef.current;
    const remaining = Math.max(0, WEB_LOADER_MIN_DURATION_MS - elapsed);

    if (remaining === 0) {
      setShowWebLoader(false);
      setPageReady(true);
      return;
    }

    webLoaderTimeoutRef.current = setTimeout(() => {
      webLoaderTimeoutRef.current = null;
      setShowWebLoader(false);
      setPageReady(true);
    }, remaining);
  }

  function closeDrawer() {
    setDrawerOpen(false);
  }

  function openSearchSheet() {
    closeDrawer();
    setSearchSheetOpen(true);
  }

  function closeSearchSheet() {
    setSearchSheetOpen(false);
    setSearchQuery('');
  }

  function openRoute(path: string) {
    const nextUrl = buildRouteUrl(path);
    const nextRoute = [...BOTTOM_NAV_ROUTES, ...DRAWER_ROUTES].find((route) => route.path === path);
    setCurrentUrl(nextUrl);
    setCurrentTitle(nextRoute?.label || getRouteForUrl(nextUrl)?.label || 'Insights');
    setWebError(null);
    closeDrawer();
    closeSearchSheet();
  }

  function resetAuthFeedback() {
    setAuthError(null);
    setAuthNotice(null);
    setFieldErrors({});
  }

  function navigateTo(screen: Exclude<NativeScreen, 'web'>, direction: NativeTransitionDirection = 'forward') {
    resetAuthFeedback();

    const currentScreen = (transitioningToScreen || nativeScreen) as NativeAppScreen;
    if (currentScreen === screen) {
      return;
    }

    nativeScreenTransitionRef.current?.stop();
    setTransitioningFromScreen(currentScreen);
    setTransitioningToScreen(screen);
    nativeScreenTranslate.setValue(direction === 'forward' ? SCREEN_WIDTH * 0.92 : -SCREEN_WIDTH * 0.92);
    previousNativeScreenTranslate.setValue(0);
    previousNativeScreenOpacity.setValue(1);

    nativeScreenTransitionRef.current = Animated.parallel([
      Animated.timing(nativeScreenTranslate, {
        toValue: 0,
        duration: 760,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(previousNativeScreenTranslate, {
        toValue: direction === 'forward' ? -SCREEN_WIDTH * 1.08 : SCREEN_WIDTH * 1.08,
        duration: 760,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(previousNativeScreenOpacity, {
        toValue: 0.82,
        duration: 760,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
    ]);

    nativeScreenTransitionRef.current.start(() => {
      setNativeScreen(screen);
      setTransitioningFromScreen(null);
      setTransitioningToScreen(null);
      nativeScreenTranslate.setValue(0);
      previousNativeScreenTranslate.setValue(0);
      previousNativeScreenOpacity.setValue(1);
      nativeScreenTransitionRef.current = null;
    });
  }

  async function shareCurrentPage() {
    try {
      await Share.share({
        title: currentTitle,
        message: currentUrl,
        url: currentUrl,
      });
    } catch (error) {
      Alert.alert('Share unavailable', 'The native share sheet could not be opened.');
    }
  }

  async function openCurrentPageExternally() {
    try {
      await Linking.openURL(currentUrl);
    } catch (error) {
      Alert.alert('Open failed', 'The current page could not be opened in the system browser.');
    }
  }

  async function openWebsiteInBrowser() {
    try {
      await Linking.openURL(BASE_URL);
    } catch (error) {
      Alert.alert('Open failed', 'The website could not be opened in the system browser.');
    }
  }

  async function requestNotifications() {
    try {
      const permission = await Notifications.requestPermissionsAsync();

      if (permission.status !== 'granted') {
        Alert.alert('Notifications not enabled', 'Notification permission was not granted on this device.');
        return;
      }

      Alert.alert('Notifications ready', 'Notification permission is enabled for the mobile shell.');
    } catch (error) {
      Alert.alert('Notifications unavailable', 'Notification permissions could not be requested in this session.');
    }
  }

  async function launchCamera() {
    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();

      if (!permission.granted) {
        Alert.alert('Camera access needed', 'Allow camera access in Expo Go to use this native action.');
        return;
      }

      const result = await ImagePicker.launchCameraAsync({
        allowsEditing: true,
        quality: 0.7,
      });

      if (!result.canceled && result.assets.length > 0) {
        setCapturedImageUri(result.assets[0].uri);
      }
    } catch (error) {
      Alert.alert('Camera unavailable', 'Launching the native camera failed.');
    }
  }

  function reloadPage() {
    setWebError(null);
    webViewRef.current?.reload();
  }

  async function postMobileAuth(path: string, payload: Record<string, string>) {
    const response = await fetch(buildRouteUrl(path), {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    let data: MobileApiResponse = {};
    try {
      data = (await response.json()) as MobileApiResponse;
    } catch {
      data = {
        ok: false,
        message: 'The server returned an unexpected response.',
      };
    }

    return { response, data };
  }

  function applyFieldErrors(nextFieldErrors?: Record<string, string[]>) {
    setFieldErrors(nextFieldErrors || {});
  }

  function getFieldError(name: string) {
    return fieldErrors[name]?.[0] || '';
  }

  function getErrorText(error: unknown) {
    if (error instanceof Error && error.message) {
      return error.message;
    }

    if (typeof error === 'string' && error.trim()) {
      return error.trim();
    }

    return 'Network request failed.';
  }

  function buildReachabilityError(prefix: string, error: unknown) {
    return `${prefix} Tried ${BASE_URL_LABEL}. ${getErrorText(error)}`;
  }

  async function handleNativeLoginSubmit() {
    if (isSubmitting) {
      return;
    }

    resetAuthFeedback();
    setIsSubmitting(true);

    try {
      const { data } = await postMobileAuth(MOBILE_LOGIN_PATH, {
        username,
        password,
      });

      if (data.requiresTwoFactor) {
        setAuthNotice(data.message || 'Enter your authentication code to continue.');
        setNativeScreen('twoFactor');
        return;
      }

      if (!data.ok || !data.sessionUrl) {
        setAuthError(data.message || 'Unable to sign in.');
        applyFieldErrors(data.fieldErrors);
        return;
      }

      setCurrentUrl(data.sessionUrl);
      setCurrentTitle('Client Portal');
      setWebError(null);
      beginWebLoader();
      setDrawerOpen(false);
      setNativeScreen('web');
    } catch (error) {
      console.warn('Mobile login request failed', buildRouteUrl(MOBILE_LOGIN_PATH), error);
      setAuthError(buildReachabilityError('Unable to reach the website right now.', error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleTwoFactorSubmit() {
    if (isSubmitting) {
      return;
    }

    resetAuthFeedback();
    setIsSubmitting(true);

    try {
      const { data } = await postMobileAuth(MOBILE_LOGIN_PATH, {
        username,
        password,
        otpCode,
      });

      if (!data.ok || !data.sessionUrl) {
        setAuthError(data.message || 'Unable to verify your code.');
        applyFieldErrors(data.fieldErrors);
        return;
      }

      setCurrentUrl(data.sessionUrl);
      setCurrentTitle('Client Portal');
      setWebError(null);
      beginWebLoader();
      setDrawerOpen(false);
      setNativeScreen('web');
    } catch (error) {
      console.warn('Mobile 2FA request failed', buildRouteUrl(MOBILE_LOGIN_PATH), error);
      setAuthError(buildReachabilityError('Unable to verify your code right now.', error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleUsernameRecoverySubmit() {
    if (isSubmitting) {
      return;
    }

    resetAuthFeedback();
    setIsSubmitting(true);

    try {
      const { data } = await postMobileAuth(MOBILE_USERNAME_RECOVERY_PATH, {
        email: recoveryEmail,
      });

      if (!data.ok) {
        setAuthError(data.message || 'Unable to send username recovery email.');
        applyFieldErrors(data.fieldErrors);
        return;
      }

      setAuthNotice(data.message || 'If an account exists for that email, a username reminder has been sent.');
    } catch (error) {
      console.warn('Mobile username recovery request failed', buildRouteUrl(MOBILE_USERNAME_RECOVERY_PATH), error);
      setAuthError(buildReachabilityError('Unable to send username recovery email right now.', error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handlePasswordResetSubmit() {
    if (isSubmitting) {
      return;
    }

    resetAuthFeedback();
    setIsSubmitting(true);

    try {
      const { data } = await postMobileAuth(MOBILE_PASSWORD_RESET_PATH, {
        email: passwordResetEmail,
      });

      if (!data.ok) {
        setAuthError(data.message || 'Unable to send password reset email.');
        applyFieldErrors(data.fieldErrors);
        return;
      }

      setAuthNotice(data.message || 'If an account exists for that email, a password reset link has been sent.');
    } catch (error) {
      console.warn('Mobile password reset request failed', buildRouteUrl(MOBILE_PASSWORD_RESET_PATH), error);
      setAuthError(buildReachabilityError('Unable to send password reset email right now.', error));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleLoadEnd() {
    finishWebLoader();
    webViewRef.current?.injectJavaScript(MOBILE_WEBVIEW_CLEANUP_SCRIPT);
  }

  function handleNavigationStateChange(navigationState: {
    url: string;
    title?: string | null;
    canGoBack: boolean;
  }) {
    if (navigationState.url.startsWith(buildRouteUrl('/login/'))) {
      resetAuthFeedback();
      setOtpCode('');
      setNativeScreen('landing');
      setCurrentTitle('Insights');
      return;
    }

    setCurrentUrl(markMobileAppUrl(navigationState.url));
    setWebError(null);

    if (navigationState.title) {
      setCurrentTitle(navigationState.title);
      return;
    }

    setCurrentTitle(getRouteForUrl(navigationState.url)?.label || 'Insights');
  }

  function handleShouldStartLoad(request: {
    url: string;
    isTopFrame?: boolean;
    mainDocumentURL?: string;
  }) {
    if (request.isTopFrame === false) {
      return true;
    }

    if (
      request.url.startsWith('about:') ||
      request.url.startsWith('data:') ||
      request.url.startsWith('blob:')
    ) {
      return true;
    }

    if (!request.url.startsWith('http://') && !request.url.startsWith('https://')) {
      Linking.openURL(request.url).catch(function () {
        Alert.alert('Unsupported link', 'This link must be opened outside the embedded browser.');
      });
      return false;
    }

    if (request.url.startsWith(BASE_URL)) {
      const mobileUrl = markMobileAppUrl(request.url);

      if (mobileUrl !== request.url) {
        if (request.mainDocumentURL && request.mainDocumentURL !== request.url) {
          return true;
        }

        setCurrentUrl(mobileUrl);
        return false;
      }
    }

    return true;
  }

  const headerLabel = currentTitle || getRouteForUrl(currentUrl)?.label || 'Insights';

  function renderAuthMessage() {
    if (!authError && !authNotice) {
      return null;
    }

    const isError = Boolean(authError);
    return (
      <View style={[styles.authMessage, isError ? styles.authMessageError : styles.authMessageSuccess]}>
        <Text style={[styles.authMessageText, isError ? styles.authMessageTextError : styles.authMessageTextSuccess]}>
          {authError || authNotice}
        </Text>
      </View>
    );
  }

  function renderFieldError(name: string) {
    const message = getFieldError(name);
    if (!message) {
      return null;
    }

    return <Text style={styles.fieldError}>{message}</Text>;
  }

  function renderTextField(options: {
    label: string;
    value: string;
    onChangeText: (value: string) => void;
    placeholder: string;
    secureTextEntry?: boolean;
    keyboardType?: 'default' | 'email-address' | 'numeric';
    autoCapitalize?: 'none' | 'sentences' | 'words' | 'characters';
    autoComplete?: 'username' | 'password' | 'email';
    errorKey: string;
  }) {
    return (
      <View style={styles.fieldRow}>
        <Text style={styles.fieldLabel}>{options.label}</Text>
        <TextInput
          value={options.value}
          onChangeText={options.onChangeText}
          placeholder={options.placeholder}
          placeholderTextColor="#8ba2b9"
          style={styles.fieldInput}
          secureTextEntry={options.secureTextEntry}
          keyboardType={options.keyboardType}
          autoCapitalize={options.autoCapitalize || 'none'}
          autoCorrect={false}
          autoComplete={options.autoComplete}
        />
        {renderFieldError(options.errorKey)}
      </View>
    );
  }

  function renderAuthScreenLayout(options: {
    eyebrow: string;
    title: string;
    copy: string;
    topContent?: ReactNode;
    body?: ReactNode;
    footer: ReactNode;
    topSectionStyle?: object;
    eyebrowStyle?: object;
    titleStyle?: object;
    copyStyle?: object;
  }) {
    return (
      <KeyboardAvoidingView behavior="padding" style={styles.authShell}>
        <ScrollView bounces={false} contentContainerStyle={styles.authScrollContent} keyboardShouldPersistTaps="handled" overScrollMode="never">
          <View style={styles.authContent}>
            <View style={[styles.authTopSection, options.topSectionStyle]}>
              <Text style={[styles.authEyebrow, options.eyebrowStyle]}>{options.eyebrow}</Text>
              <Text style={[styles.authTitle, options.titleStyle]}>{options.title}</Text>
              {options.topContent}
              <Text style={[styles.authCopy, options.copyStyle]}>{options.copy}</Text>
            </View>

            {options.body ? <View style={styles.authBodySection}>{options.body}</View> : <View style={styles.authBodySpacer} />}

            <View style={styles.authFooterSection}>{options.footer}</View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    );
  }

  function renderDynamicBrandIcon(variant: 'landing' | 'loading' = 'landing') {
    const barOneHeight = landingDataMotion.interpolate({
      inputRange: [0, 0.35, 0.7, 1],
      outputRange: variant === 'landing' ? [46, 86, 58, 72] : [20, 38, 26, 32],
    });
    const barTwoHeight = landingDataMotion.interpolate({
      inputRange: [0, 0.3, 0.65, 1],
      outputRange: variant === 'landing' ? [22, 56, 30, 44] : [10, 24, 14, 20],
    });
    const barThreeHeight = landingDataMotion.interpolate({
      inputRange: [0, 0.25, 0.75, 1],
      outputRange: variant === 'landing' ? [38, 72, 52, 64] : [16, 32, 22, 28],
    });

    const wrapperStyle = variant === 'landing' ? styles.landingIconWrap : styles.loadingIconWrap;
    const iconStyle = variant === 'landing' ? styles.landingDynamicIcon : styles.loadingDynamicIcon;
    const barStyle = variant === 'landing' ? styles.landingDynamicBar : styles.loadingDynamicBar;

    return (
      <View style={wrapperStyle}>
        <View style={iconStyle}>
          <Animated.View style={[barStyle, styles.landingDynamicBarLeft, { height: barOneHeight }]} />
          <Animated.View style={[barStyle, styles.landingDynamicBarCenter, { height: barTwoHeight }]} />
          <Animated.View style={[barStyle, styles.landingDynamicBarRight, { height: barThreeHeight }]} />
        </View>
      </View>
    );
  }

  function renderHamburgerIcon() {
    return <Ionicons color="#f8fafc" name="menu" size={22} />;
  }

  function renderSearchIcon() {
    return <Ionicons color="#f8fafc" name={searchSheetOpen ? 'search' : 'search-outline'} size={20} />;
  }

  function getBottomNavIconName(routeKey: string, isActive: boolean): keyof typeof Ionicons.glyphMap {
    switch (routeKey) {
      case 'dashboard':
        return isActive ? 'home' : 'home-outline';
      case 'products':
        return isActive ? 'bag-handle' : 'bag-handle-outline';
      case 'services':
        return isActive ? 'construct' : 'construct-outline';
      case 'contact':
        return isActive ? 'call' : 'call-outline';
      default:
        return isActive ? 'ellipse' : 'ellipse-outline';
    }
  }

  function renderBottomNavBarContent() {
    return (
      <>
        <Pressable onPress={openSearchSheet} style={[styles.bottomSearchButton, searchSheetOpen && styles.bottomSearchButtonActive]}>
          {renderSearchIcon()}
        </Pressable>

        <View style={styles.bottomNavItems}>
          {BOTTOM_NAV_ROUTES.map((route) => {
            const isActive = activeRoute?.path === route.path;

            return (
              <Pressable key={route.key} onPress={() => openRoute(route.path)} style={[styles.bottomNavButton, isActive && styles.bottomNavButtonActive]}>
                <Ionicons
                  color={isActive ? '#f8fafc' : '#c7d4e4'}
                  name={getBottomNavIconName(route.key, isActive)}
                  size={22}
                  style={styles.bottomNavIcon}
                />
                <Text
                  adjustsFontSizeToFit
                  minimumFontScale={0.82}
                  numberOfLines={1}
                  style={[styles.bottomNavLabel, isActive && styles.bottomNavLabelActive]}
                >
                  {route.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </>
    );
  }

  function renderBottomNav() {
    const content = renderBottomNavBarContent();

    return (
      <View style={styles.bottomNavWrap}>
        <View style={Platform.OS === 'ios' ? styles.bottomNavBarGlass : styles.bottomNavBar}>
          {Platform.OS === 'ios' ? <View style={styles.bottomNavGlassTint} /> : null}
          <View style={styles.bottomNavBarContent}>{content}</View>
        </View>
      </View>
    );
  }

  function renderSearchSheet() {
    if (!searchSheetOpen) {
      return null;
    }

    return (
      <>
        <Pressable onPress={closeSearchSheet} style={styles.searchSheetBackdrop} />
        <View style={styles.searchSheet}>
          <Text style={styles.searchSheetTitle}>Search Navigation</Text>
          <TextInput
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder="Search pages"
            placeholderTextColor="#90a3b9"
            style={styles.searchSheetInput}
            autoCapitalize="none"
            autoCorrect={false}
          />

          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.searchSheetResults}>
            {searchResults.map((route) => (
              <Pressable key={route.key} onPress={() => openRoute(route.path)} style={styles.searchSheetLink}>
                <Text style={styles.searchSheetLinkText}>{route.label}</Text>
                <Text style={styles.searchSheetLinkMeta}>{route.path}</Text>
              </Pressable>
            ))}

            {searchResults.length === 0 ? <Text style={styles.searchSheetEmpty}>No matching pages.</Text> : null}
          </ScrollView>
        </View>
      </>
    );
  }

  function renderNativeLanding() {
    return renderAuthScreenLayout({
      eyebrow: 'Client Portal',
      title: 'Welcome to Miranda Insights',
      copy:
        "Log in to access to your client portal dashboard. If you don't have an account with us yet, please book a consultation with us to get started.",
      topContent: (
        <View style={styles.landingVisualStage}>{renderDynamicBrandIcon('landing')}</View>
      ),
      topSectionStyle: styles.landingTopSection,
      eyebrowStyle: styles.landingTextCentered,
      titleStyle: [styles.landingTextCentered, styles.landingTitle],
      copyStyle: styles.landingCopyCentered,
      footer: (
        <View style={[styles.authActionsColumn, styles.landingActionsColumn]}>
          <Pressable onPress={() => navigateTo('login', 'forward')} style={[styles.authButton, styles.authPrimaryButton]}>
            <Text style={styles.authPrimaryButtonText}>Log In</Text>
          </Pressable>
          <Pressable onPress={openWebsiteInBrowser} style={[styles.authButton, styles.authSecondaryButton]}>
            <Text style={styles.authSecondaryButtonText}>Book Consultation</Text>
          </Pressable>
        </View>
      ),
    });
  }

  function renderNativeLogin() {
    return renderAuthScreenLayout({
      eyebrow: 'Client Portal',
      title: 'Log In',
      copy: 'Enter your username and password to access your Insights account.',
      body: (
        <>
          {renderAuthMessage()}
          {renderTextField({
            label: 'Username',
            value: username,
            onChangeText: setUsername,
            placeholder: 'Username',
            autoComplete: 'username',
            errorKey: 'username',
          })}
          {renderTextField({
            label: 'Password',
            value: password,
            onChangeText: setPassword,
            placeholder: 'Password',
            secureTextEntry: true,
            autoComplete: 'password',
            errorKey: 'password',
          })}
        </>
      ),
      footer: (
        <>
          <Pressable onPress={handleNativeLoginSubmit} style={[styles.authButton, styles.authPrimaryButton, isSubmitting && styles.authButtonDisabled]}>
            <Text style={styles.authPrimaryButtonText}>{isSubmitting ? 'Signing in...' : 'Log In'}</Text>
          </Pressable>

          <View style={styles.authLinks}>
            <Pressable onPress={() => navigateTo('forgotUsername', 'forward')}><Text style={styles.authLinkText}>Forgot username?</Text></Pressable>
            <Pressable onPress={() => navigateTo('forgotPassword', 'forward')}><Text style={styles.authLinkText}>Forgot password?</Text></Pressable>
            <Pressable onPress={() => navigateTo('landing', 'back')}><Text style={styles.authLinkText}>Back</Text></Pressable>
          </View>
        </>
      ),
    });
  }

  function renderTwoFactorScreen() {
    return renderAuthScreenLayout({
      eyebrow: 'Client Portal',
      title: 'Authentication Code',
      copy: 'Open your authenticator app and enter the current 6-digit code to complete sign in.',
      body: (
        <>
          {renderAuthMessage()}
          {renderTextField({
            label: 'Authentication Code',
            value: otpCode,
            onChangeText: setOtpCode,
            placeholder: '123456',
            keyboardType: 'numeric',
            errorKey: 'otpCode',
          })}
        </>
      ),
      footer: (
        <>
          <Pressable onPress={handleTwoFactorSubmit} style={[styles.authButton, styles.authPrimaryButton, isSubmitting && styles.authButtonDisabled]}>
            <Text style={styles.authPrimaryButtonText}>{isSubmitting ? 'Verifying...' : 'Verify and Continue'}</Text>
          </Pressable>
          <View style={styles.authLinks}>
            <Pressable onPress={() => navigateTo('login', 'back')}><Text style={styles.authLinkText}>Back to login</Text></Pressable>
          </View>
        </>
      ),
    });
  }

  function renderUsernameRecoveryScreen() {
    return renderAuthScreenLayout({
      eyebrow: 'Account Recovery',
      title: 'Forgot Username',
      copy: 'Enter the email address tied to your account and we will send your username.',
      body: (
        <>
          {renderAuthMessage()}
          {renderTextField({
            label: 'Email Address',
            value: recoveryEmail,
            onChangeText: setRecoveryEmail,
            placeholder: 'you@example.com',
            keyboardType: 'email-address',
            autoComplete: 'email',
            errorKey: 'email',
          })}
        </>
      ),
      footer: (
        <>
          <Pressable onPress={handleUsernameRecoverySubmit} style={[styles.authButton, styles.authPrimaryButton, isSubmitting && styles.authButtonDisabled]}>
            <Text style={styles.authPrimaryButtonText}>{isSubmitting ? 'Sending...' : 'Send Username'}</Text>
          </Pressable>
          <View style={styles.authLinks}>
            <Pressable onPress={() => navigateTo('login', 'back')}><Text style={styles.authLinkText}>Back to login</Text></Pressable>
          </View>
        </>
      ),
    });
  }

  function renderPasswordResetScreen() {
    return renderAuthScreenLayout({
      eyebrow: 'Password Recovery',
      title: 'Forgot Password',
      copy: 'Enter your account email address and we will send a password reset link.',
      body: (
        <>
          {renderAuthMessage()}
          {renderTextField({
            label: 'Email Address',
            value: passwordResetEmail,
            onChangeText: setPasswordResetEmail,
            placeholder: 'you@example.com',
            keyboardType: 'email-address',
            autoComplete: 'email',
            errorKey: 'email',
          })}
        </>
      ),
      footer: (
        <>
          <Pressable onPress={handlePasswordResetSubmit} style={[styles.authButton, styles.authPrimaryButton, isSubmitting && styles.authButtonDisabled]}>
            <Text style={styles.authPrimaryButtonText}>{isSubmitting ? 'Sending...' : 'Send Reset Link'}</Text>
          </Pressable>
          <View style={styles.authLinks}>
            <Pressable onPress={() => navigateTo('login', 'back')}><Text style={styles.authLinkText}>Back to login</Text></Pressable>
          </View>
        </>
      ),
    });
  }

  function renderNativeScreen(screen: NativeAppScreen) {
    switch (screen) {
      case 'login':
        return renderNativeLogin();
      case 'twoFactor':
        return renderTwoFactorScreen();
      case 'forgotUsername':
        return renderUsernameRecoveryScreen();
      case 'forgotPassword':
        return renderPasswordResetScreen();
      case 'landing':
      default:
        return renderNativeLanding();
    }
  }

  return (
    <View style={styles.safeArea}>
      <StatusBar hidden style="light" />

      {nativeScreen !== 'web' ? (
        <View style={styles.nativeScreenViewport}>
          {transitioningFromScreen ? (
            <Animated.View
              pointerEvents="none"
              renderToHardwareTextureAndroid
              shouldRasterizeIOS
              style={[
                styles.nativeScreenStage,
                styles.nativeScreenStageOverlay,
                {
                  opacity: previousNativeScreenOpacity,
                  transform: [{ translateX: previousNativeScreenTranslate }],
                },
              ]}
            >
              {renderNativeScreen(transitioningFromScreen)}
            </Animated.View>
          ) : null}

          <Animated.View
            renderToHardwareTextureAndroid
            shouldRasterizeIOS
            style={[
              styles.nativeScreenStage,
              styles.nativeScreenStageOverlay,
              { transform: [{ translateX: nativeScreenTranslate }] },
            ]}
          >
            {renderNativeScreen((transitioningToScreen || nativeScreen) as NativeAppScreen)}
          </Animated.View>
        </View>
      ) : null}

      {nativeScreen === 'web' ? (
        <>
          <SafeAreaView style={styles.appShell}>
            <View style={styles.header}>
              <Pressable onPress={() => setDrawerOpen(true)} style={styles.headerButton}>
                {renderHamburgerIcon()}
              </Pressable>

              <View style={styles.headerCenter}>
                <Text numberOfLines={1} style={styles.headerTitle}>{headerLabel}</Text>
              </View>

              <View style={styles.headerSpacer} />
            </View>

            <View style={styles.webViewContainer}>
              <WebView
                bounces={false}
                contentInsetAdjustmentBehavior="never"
                ref={webViewRef}
                overScrollMode="never"
                pullToRefreshEnabled={false}
                source={{ uri: currentUrl }}
                style={showWebLoader ? styles.webViewHidden : styles.webView}
                injectedJavaScript={MOBILE_WEBVIEW_CLEANUP_SCRIPT}
                injectedJavaScriptBeforeContentLoaded={MOBILE_WEBVIEW_CLEANUP_SCRIPT}
                onLoadEnd={handleLoadEnd}
                onNavigationStateChange={handleNavigationStateChange}
                onShouldStartLoadWithRequest={handleShouldStartLoad}
                onError={(event) => {
                  clearWebLoaderTimeout();
                  setShowWebLoader(false);
                  setWebError(event.nativeEvent.description);
                }}
                sharedCookiesEnabled
                setSupportMultipleWindows={false}
                allowsBackForwardNavigationGestures
              />

              {webError ? (
                <View style={styles.errorCard}>
                  <Text style={styles.errorTitle}>Unable to reach the Django site</Text>
                  <Text style={styles.errorCopy}>Current URL: {BASE_URL}</Text>
                  <Text style={styles.errorCopy}>Default local URL: {DEFAULT_BASE_URL}</Text>
                  <Text style={styles.errorCopy}>{webError}</Text>
                  <Pressable onPress={reloadPage} style={styles.errorButton}>
                    <Text style={styles.errorButtonText}>Retry</Text>
                  </Pressable>
                </View>
              ) : null}
            </View>

            {renderBottomNav()}
          </SafeAreaView>

          {showWebLoader && !webError ? (
            <View pointerEvents="none" style={styles.loadingScreenOverlay}>
              <View style={styles.loadingState}>
                {renderDynamicBrandIcon('loading')}
                <Text style={styles.loadingStateText}>Loading Insights...</Text>
              </View>
            </View>
          ) : null}

          {renderSearchSheet()}

          {drawerOpen ? <Pressable onPress={closeDrawer} style={styles.drawerBackdrop} /> : null}

          <Animated.View style={[styles.drawer, { transform: [{ translateX: drawerOffset }] }]}> 
            <ScrollView contentContainerStyle={styles.drawerContent}>
              <View style={styles.drawerHeader}>
                <Text style={styles.drawerEyebrow}>Miranda Insights Mobile</Text>
                <Text style={styles.drawerTitle}>SIDE MENU</Text>
              </View>

              <View style={styles.drawerSection}>
                <Text style={styles.drawerSectionTitle}>Navigate</Text>
                {DRAWER_ROUTES.map((route) => (
                  <Pressable key={route.key} onPress={() => openRoute(route.path)} style={styles.drawerLinkRow}>
                    <Text style={styles.drawerLinkText}>{route.label}</Text>
                  </Pressable>
                ))}
              </View>

              <View style={styles.drawerSection}>
                <Text style={styles.drawerSectionTitle}>Other Actions</Text>
                <Pressable onPress={openCurrentPageExternally} style={styles.drawerLinkRow}>
                  <Text style={styles.drawerActionText}>Open in default browser</Text>
                </Pressable>
                <Pressable onPress={requestNotifications} style={styles.drawerLinkRow}>
                  <Text style={styles.drawerActionText}>Enable notifications</Text>
                </Pressable>
              </View>

              {capturedImageUri ? (
                <View style={styles.drawerSection}>
                  <Text style={styles.drawerSectionTitle}>Latest capture</Text>
                  <Image source={{ uri: capturedImageUri }} style={styles.capturePreview} />
                </View>
              ) : null}
            </ScrollView>
          </Animated.View>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#0c111b',
  },
  authShell: {
    flex: 1,
    backgroundColor: '#0c111b',
    paddingBottom: 0,
  },
  nativeScreenStage: {
    flex: 1,
    backgroundColor: '#0c111b',
    backfaceVisibility: 'hidden',
  },
  nativeScreenViewport: {
    flex: 1,
    overflow: 'hidden',
    position: 'relative',
    backgroundColor: '#0c111b',
  },
  nativeScreenStageOverlay: {
    position: 'absolute',
    inset: 0,
  },
  authScrollContent: {
    flexGrow: 1,
    paddingHorizontal: 24,
    paddingTop: 52,
    paddingBottom: 168,
  },
  authContent: {
    flexGrow: 1,
    width: '100%',
    minHeight: '100%',
    justifyContent: 'space-between',
    gap: 24,
  },
  authTopSection: {
    gap: 16,
    paddingTop: 28,
  },
  landingTopSection: {
    alignItems: 'center',
    paddingTop: 84,
  },
  landingTextCentered: {
    textAlign: 'center',
  },
  landingTitle: {
    fontSize: 38,
    lineHeight: 44,
  },
  landingCopyCentered: {
    textAlign: 'center',
    maxWidth: 320,
  },
  authBodySection: {
    gap: 16,
    justifyContent: 'center',
  },
  landingVisualStage: {
    minHeight: 156,
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  landingIconWrap: {
    width: 150,
    height: 150,
    borderRadius: 38,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(9, 16, 30, 0.96)',
    borderWidth: 1,
    borderColor: 'rgba(116, 149, 228, 0.42)',
    shadowColor: '#050b16',
    shadowOpacity: 0.28,
    shadowRadius: 22,
    elevation: 14,
  },
  landingDynamicIcon: {
    width: 92,
    height: 96,
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'center',
    gap: 18,
  },
  landingDynamicBar: {
    width: 18,
    borderRadius: 4,
  },
  loadingIconWrap: {
    width: 74,
    height: 74,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(9, 16, 30, 0.9)',
    borderWidth: 1,
    borderColor: 'rgba(116, 149, 228, 0.36)',
  },
  loadingDynamicIcon: {
    width: 44,
    height: 40,
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'center',
    gap: 8,
  },
  loadingDynamicBar: {
    width: 8,
    borderRadius: 3,
  },
  landingDynamicBarLeft: {
    backgroundColor: '#6797ea',
  },
  landingDynamicBarCenter: {
    backgroundColor: '#8d93f3',
  },
  landingDynamicBarRight: {
    backgroundColor: '#8d93f3',
  },
  authBodySpacer: {
    flex: 1,
  },
  authFooterSection: {
    gap: 16,
    paddingBottom: 92,
  },
  authEyebrow: {
    color: AUTH_ACCENT_COLOR,
    fontSize: 12,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 1.2,
  },
  authTitle: {
    color: '#f8fafc',
    fontSize: 30,
    fontWeight: '800',
  },
  authCopy: {
    color: '#b8c8d9',
    fontSize: 14,
    lineHeight: 22,
  },
  authMessage: {
    borderRadius: 16,
    borderWidth: 1,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  authMessageError: {
    backgroundColor: 'rgba(127, 29, 29, 0.28)',
    borderColor: '#b91c1c',
  },
  authMessageSuccess: {
    backgroundColor: 'rgba(20, 83, 45, 0.28)',
    borderColor: '#15803d',
  },
  authMessageText: {
    fontSize: 13,
    lineHeight: 19,
  },
  authMessageTextError: {
    color: '#fecaca',
  },
  authMessageTextSuccess: {
    color: '#dcfce7',
  },
  fieldRow: {
    gap: 8,
  },
  fieldLabel: {
    color: '#f8fafc',
    fontSize: 14,
    fontWeight: '700',
  },
  fieldInput: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#27405f',
    backgroundColor: '#10253d',
    color: '#f8fafc',
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 14,
  },
  fieldError: {
    color: '#fca5a5',
    fontSize: 12,
    lineHeight: 18,
  },
  authActionsColumn: {
    gap: 12,
  },
  landingActionsColumn: {
    marginTop: -18,
  },
  authButton: {
    minHeight: 52,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
  },
  authButtonDisabled: {
    opacity: 0.7,
  },
  authPrimaryButton: {
    backgroundColor: AUTH_ACCENT_COLOR,
  },
  authPrimaryButtonText: {
    color: '#0f172a',
    fontSize: 15,
    fontWeight: '800',
  },
  authSecondaryButton: {
    backgroundColor: '#10253d',
    borderWidth: 1,
    borderColor: '#27405f',
  },
  authSecondaryButtonText: {
    color: '#f8fafc',
    fontSize: 15,
    fontWeight: '800',
  },
  authLinks: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 14,
    justifyContent: 'center',
  },
  authLinkText: {
    color: AUTH_ACCENT_COLOR,
    fontSize: 13,
    fontWeight: '700',
  },
  appShell: {
    flex: 1,
    backgroundColor: '#0c111b',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 12,
    backgroundColor: '#0c111b',
    borderBottomWidth: 1,
    borderBottomColor: '#17304c',
  },
  headerButton: {
    width: 46,
    height: 46,
    borderRadius: 999,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#11233a',
  },
  headerSpacer: {
    minWidth: 46,
  },
  headerCenter: {
    flex: 1,
    paddingHorizontal: 12,
  },
  headerTitle: {
    color: '#f8fafc',
    fontSize: 18,
    fontWeight: '700',
  },
  webViewContainer: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  webView: {
    flex: 1,
  },
  webViewHidden: {
    flex: 1,
    opacity: 0,
  },
  loadingScreenOverlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 50,
    elevation: 50,
    backgroundColor: '#07111f',
  },
  loadingState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#07111f',
    gap: 18,
  },
  loadingStateText: {
    color: '#d8e5f2',
    fontSize: 15,
  },
  bottomNavWrap: {
    paddingHorizontal: 14,
    paddingTop: 10,
    paddingBottom: 10,
    backgroundColor: '#0c111b',
  },
  bottomNavBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 10,
    paddingVertical: 10,
    borderRadius: 28,
    borderWidth: 1,
    borderColor: 'rgba(150, 180, 220, 0.18)',
    backgroundColor: Platform.select({
      ios: 'rgba(18, 31, 51, 0.72)',
      default: 'rgba(14, 24, 40, 0.96)',
    }),
    shadowColor: '#020617',
    shadowOpacity: 0.2,
    shadowRadius: 18,
    elevation: 14,
  },
  bottomNavBarGlass: {
    overflow: 'hidden',
    borderRadius: 28,
    borderWidth: 1,
    borderColor: 'rgba(218, 230, 244, 0.18)',
    backgroundColor: 'rgba(28, 41, 62, 0.78)',
    shadowColor: '#020617',
    shadowOpacity: 0.24,
    shadowRadius: 20,
    elevation: 16,
  },
  bottomNavGlassTint: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(244, 248, 255, 0.08)',
  },
  bottomNavBarContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  bottomSearchButton: {
    width: 46,
    height: 46,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(103, 151, 234, 0.12)',
    borderWidth: 1,
    borderColor: 'rgba(103, 151, 234, 0.22)',
  },
  bottomSearchButtonActive: {
    backgroundColor: 'rgba(103, 151, 234, 0.22)',
    borderColor: 'rgba(103, 151, 234, 0.42)',
  },
  bottomNavItems: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 4,
  },
  bottomNavButton: {
    flex: 1,
    minHeight: 48,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
    paddingHorizontal: 4,
  },
  bottomNavButtonActive: {
    backgroundColor: 'rgba(248, 250, 252, 0.14)',
  },
  bottomNavIcon: {
    marginBottom: 1,
  },
  bottomNavLabel: {
    color: '#ccd8e8',
    fontSize: 10,
    fontWeight: '700',
    textAlign: 'center',
  },
  bottomNavLabelActive: {
    color: '#f8fafc',
  },
  searchSheetBackdrop: {
    position: 'absolute',
    inset: 0,
    backgroundColor: 'rgba(1, 8, 18, 0.5)',
    zIndex: 39,
  },
  searchSheet: {
    position: 'absolute',
    left: 16,
    right: 16,
    bottom: 108,
    maxHeight: '56%',
    borderRadius: 28,
    padding: 18,
    gap: 14,
    zIndex: 40,
    borderWidth: 1,
    borderColor: 'rgba(150, 180, 220, 0.18)',
    backgroundColor: Platform.select({
      ios: 'rgba(12, 20, 34, 0.9)',
      default: '#0c111b',
    }),
  },
  searchSheetTitle: {
    color: '#f8fafc',
    fontSize: 18,
    fontWeight: '800',
  },
  searchSheetInput: {
    minHeight: 48,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#27405f',
    backgroundColor: '#10253d',
    color: '#f8fafc',
    paddingHorizontal: 14,
    fontSize: 15,
  },
  searchSheetResults: {
    gap: 10,
    paddingBottom: 8,
  },
  searchSheetLink: {
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 16,
    backgroundColor: '#10253d',
    gap: 4,
  },
  searchSheetLinkText: {
    color: '#f8fafc',
    fontSize: 15,
    fontWeight: '700',
  },
  searchSheetLinkMeta: {
    color: '#90a3b9',
    fontSize: 12,
  },
  searchSheetEmpty: {
    color: '#90a3b9',
    fontSize: 14,
    textAlign: 'center',
    paddingVertical: 12,
  },
  errorCard: {
    position: 'absolute',
    left: 16,
    right: 16,
    top: 24,
    backgroundColor: '#fff7ed',
    borderRadius: 20,
    padding: 18,
    borderWidth: 1,
    borderColor: '#fdba74',
    gap: 8,
  },
  errorTitle: {
    color: '#9a3412',
    fontSize: 18,
    fontWeight: '700',
  },
  errorCopy: {
    color: '#7c2d12',
    fontSize: 13,
    lineHeight: 18,
  },
  errorButton: {
    alignSelf: 'flex-start',
    marginTop: 4,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 999,
    backgroundColor: '#c2410c',
  },
  errorButtonText: {
    color: '#fff',
    fontWeight: '700',
  },
  drawerBackdrop: {
    position: 'absolute',
    inset: 0,
    backgroundColor: 'rgba(1, 8, 18, 0.45)',
  },
  drawer: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: DRAWER_WIDTH,
    backgroundColor: '#07111f',
    borderRightWidth: 1,
    borderRightColor: '#17304c',
    shadowColor: '#000',
    shadowOpacity: 0.25,
    shadowRadius: 24,
    elevation: 20,
  },
  drawerContent: {
    paddingTop: 68,
    paddingHorizontal: 18,
    paddingBottom: 28,
    gap: 22,
  },
  drawerHeader: {
    padding: 18,
    borderRadius: 24,
    backgroundColor: '#0c111b',
    gap: 10,
  },
  drawerEyebrow: {
    color: AUTH_ACCENT_COLOR,
    fontSize: 12,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 1.2,
  },
  drawerTitle: {
    color: '#f8fafc',
    fontSize: 22,
    fontWeight: '800',
  },
  drawerSection: {
    gap: 10,
  },
  drawerSectionTitle: {
    color: '#f8fafc',
    fontSize: 14,
    fontWeight: '800',
  },
  drawerLinkRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(39, 64, 95, 0.8)',
  },
  drawerLinkText: {
    color: '#d9e6f3',
    fontSize: 14,
    fontWeight: '700',
  },
  drawerActionText: {
    color: '#c9d7e6',
    fontSize: 14,
    fontWeight: '600',
  },
  capturePreview: {
    width: '100%',
    height: 180,
    borderRadius: 18,
    backgroundColor: '#0c111b',
  },
});
