import { StatusBar } from 'expo-status-bar';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Ionicons } from '@expo/vector-icons';
import { type ReactNode, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Animated,
  Dimensions,
  Easing,
  Image,
  Keyboard,
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
  type AppRoute,
  BASE_URL,
  BASE_URL_LABEL,
  BOTTOM_NAV_ROUTES,
  DEFAULT_BASE_URL,
  DRAWER_ROUTES,
  EXPO_PUSH_PROJECT_ID,
  SEARCH_ROUTES,
  buildRouteUrl,
  getRouteForUrl,
  markMobileAppUrl,
} from './src/config';

const DRAWER_WIDTH = 320;
const SCREEN_WIDTH = Dimensions.get('window').width;
const SCREEN_HEIGHT = Dimensions.get('window').height;
const AUTH_ACCENT_COLOR = '#6797ea';
const WEB_LOADER_MIN_DURATION_MS = 2500;
const MOBILE_LOGIN_PATH = '/mobile-api/login/';
const MOBILE_USERNAME_RECOVERY_PATH = '/mobile-api/recover-username/';
const MOBILE_PASSWORD_RESET_PATH = '/mobile-api/password-reset/';
const MOBILE_PUSH_DEVICE_PATH = '/mobile-api/push-devices/';
const REMEMBERED_PORTAL_LAUNCH_KEY = 'insights.mobile.resumePortalOnLaunch';

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

type SearchMatch = {
  text: string;
  targetText: string;
  score: number;
};

type SearchCandidateMatch = {
  candidate: string;
  score: number;
  displayText: string;
};

type SearchContentIndex = Record<string, string[]>;
type MobileDashboardFocusTarget = 'booking' | 'newsletter';

const SEARCH_RESULT_PHRASE_LIMIT = 6;
const SEARCH_ROUTE_PHRASE_LIMIT = 36;
const SEARCH_SHEET_ANIMATION_DURATION_MS = 220;

function normalizeSearchValue(value: string) {
  return value.trim().toLowerCase();
}

function decodeHtmlEntities(value: string) {
  return value
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>');
}

function stripHtmlTags(value: string) {
  return value.replace(/<[^>]+>/g, ' ');
}

function cleanSearchText(value: string) {
  return decodeHtmlEntities(stripHtmlTags(value)).replace(/\s+/g, ' ').trim();
}

function extractMainContentHtml(html: string) {
  const mainMatch = html.match(/<main\b[^>]*class=["'][^"']*site-main[^"']*["'][^>]*>([\s\S]*?)<\/main>/i);
  return mainMatch?.[1] || html;
}

function splitSearchPhrases(text: string) {
  const cleanedText = cleanSearchText(text);
  if (!cleanedText) {
    return [];
  }

  const sentenceParts = cleanedText
    .split(/[.!?]+/)
    .map(function (part) {
      return part.trim();
    })
    .filter(Boolean);

  return sentenceParts.flatMap(function (part) {
    const clauses = part
      .split(/;|:|, (?=[A-Z0-9])/)
      .map(function (clause) {
        return clause.trim();
      })
      .filter(function (clause) {
        return clause.length >= 3 && clause.length <= 140;
      });

    return clauses.length > 0 ? clauses : [part];
  });
}

function extractSearchPhrasesFromHtml(html: string) {
  const mainHtml = extractMainContentHtml(html);
  const textTagPattern = /<(h1|h2|h3|p|li|a)\b[^>]*>([\s\S]*?)<\/\1>/gi;
  const phrases: string[] = [];
  let match: RegExpExecArray | null = null;

  while ((match = textTagPattern.exec(mainHtml)) !== null) {
    phrases.push(...splitSearchPhrases(match[2]));
  }

  return Array.from(new Set(phrases)).slice(0, SEARCH_ROUTE_PHRASE_LIMIT);
}

function getMatchingStartIndex(queryTerms: string[], candidateTerms: string[]) {
  for (let startIndex = 0; startIndex <= candidateTerms.length - queryTerms.length; startIndex += 1) {
    const matches = queryTerms.every(function (term, offset) {
      return candidateTerms[startIndex + offset].startsWith(term);
    });

    if (matches) {
      return startIndex;
    }
  }

  return -1;
}

function buildSearchDisplayText(candidate: string, query: string) {
  const originalTerms = candidate.trim().split(/\s+/).filter(Boolean);
  const normalizedTerms = originalTerms.map(function (term) {
    return normalizeSearchValue(term);
  });
  const queryTerms = normalizeSearchValue(query).split(/\s+/).filter(Boolean);
  const startIndex = getMatchingStartIndex(queryTerms, normalizedTerms);

  if (startIndex === -1) {
    return candidate;
  }

  const displayTerms = originalTerms.slice(startIndex, startIndex + 7);
  const prefix = startIndex > 0 ? '... ' : '';
  const suffix = startIndex + 7 < originalTerms.length ? ' ...' : '';
  return `${prefix}${displayTerms.join(' ')}${suffix}`;
}

function getPrefixPhraseScore(query: string, candidate: string) {
  const normalizedQuery = normalizeSearchValue(query);
  const normalizedCandidate = normalizeSearchValue(candidate);

  if (!normalizedQuery || !normalizedCandidate) {
    return 0;
  }

  const queryTerms = normalizedQuery.split(/\s+/).filter(Boolean);
  const candidateTerms = normalizedCandidate.split(/\s+/).filter(Boolean);

  if (queryTerms.length === 0 || candidateTerms.length === 0) {
    return 0;
  }

  let bestScore = 0;

  for (let startIndex = 0; startIndex <= candidateTerms.length - queryTerms.length; startIndex += 1) {
    const matches = queryTerms.every(function (term, offset) {
      return candidateTerms[startIndex + offset].startsWith(term);
    });

    if (!matches) {
      continue;
    }

    let score = 140;
    score -= startIndex * 18;
    score -= (candidateTerms.length - queryTerms.length) * 4;

    if (startIndex === 0) {
      score += 18;
    }

    if (queryTerms.length === candidateTerms.length) {
      score += 10;
    }

    if (candidateTerms[startIndex] === queryTerms[0]) {
      score += 8;
    }

    bestScore = Math.max(bestScore, score);
  }

  return bestScore;
}

function buildSearchMatch(query: string, candidate: string): SearchCandidateMatch | null {
  const normalizedQuery = normalizeSearchValue(query);
  const score = getPrefixPhraseScore(normalizedQuery, candidate);

  if (!normalizedQuery || score <= 0) {
    return null;
  }

  return {
    candidate,
    score,
    displayText: buildSearchDisplayText(candidate, normalizedQuery),
  };
}

function getNativeAuthScreenForPath(pathname: string): NativeAppScreen | null {
  if (pathname.startsWith('/login/')) {
    return 'login';
  }

  if (pathname.startsWith('/recover-username/')) {
    return 'forgotUsername';
  }

  if (pathname.startsWith('/password-reset/')) {
    return 'forgotPassword';
  }

  return null;
}

function getRouteSearchMatches(route: AppRoute, query: string, pagePhrases: string[]) {
  const queryValue = normalizeSearchValue(query);
  const defaultMatches = route.keywords.slice(0, 4).map(function (keyword) {
    return { text: keyword, targetText: keyword, score: 0 };
  });

  if (!queryValue) {
    return {
      matchesQuery: true,
      matchedTerms: defaultMatches,
      score: 0,
    };
  }

  const candidates = Array.from(
    new Set([
      route.label,
      ...pagePhrases,
      ...(pagePhrases.length === 0 ? route.keywords : []),
    ])
  );

  const matchedTerms = candidates
    .map(function (candidate) {
      return buildSearchMatch(queryValue, candidate);
    })
    .filter(function (match) {
      return Boolean(match);
    })
    .map(function (match) {
      return match as SearchCandidateMatch;
    })
    .sort(function (left, right) {
      if (right.score !== left.score) {
        return right.score - left.score;
      }

      return left.displayText.localeCompare(right.displayText);
    });

  if (matchedTerms.length === 0) {
    return {
      matchesQuery: false,
      matchedTerms: [],
      score: 0,
    };
  }

  return {
    matchesQuery: true,
    matchedTerms: matchedTerms.slice(0, SEARCH_RESULT_PHRASE_LIMIT).map(function (match) {
      return {
        text: match.displayText,
        targetText: match.candidate,
        score: match.score,
      };
    }),
    score: matchedTerms.reduce(function (total, match, index) {
      return total + match.score - index;
    }, 0),
  };
}

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

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
        style.textContent = '.site-header, .nav-overlay, .site-footer, footer.site-footer, .pwa-install-banner, .turnstile-wrap, .cf-turnstile, iframe[src*="challenges.cloudflare.com"]{display:none !important;visibility:hidden !important;height:0 !important;min-height:0 !important;overflow:hidden !important;} html, body{padding-top:0 !important;overscroll-behavior:none !important;background:#0c111b !important;} .site-main{padding-top:0 !important;} .container{width:95% !important;max-width:none !important;margin-left:auto !important;margin-right:auto !important;padding-left:0 !important;padding-right:0 !important;}';
        (document.head || document.documentElement).appendChild(style);
      }

      document.documentElement.style.setProperty('--header-height', '0px');
      document.documentElement.style.background = '#0c111b';
      document.documentElement.style.overscrollBehavior = 'none';
      document.cookie = 'insights_mobile_app=1; path=/; SameSite=Lax';

      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.getRegistrations().then(function (registrations) {
          registrations.forEach(function (registration) {
            registration.unregister();
          });
        }).catch(function () {});
      }

      if (window.caches && typeof window.caches.keys === 'function') {
        window.caches.keys().then(function (keys) {
          keys.forEach(function (key) {
            window.caches.delete(key);
          });
        }).catch(function () {});
      }

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

function buildSearchHighlightScript(phrase: string) {
  return `
    (function () {
      var phrase = ${JSON.stringify(phrase)};
      if (!phrase) {
        return true;
      }

      function clearHighlights() {
        document.querySelectorAll('span[data-insights-search-highlight="1"]').forEach(function (node) {
          var parent = node.parentNode;
          if (!parent) {
            return;
          }

          parent.replaceChild(document.createTextNode(node.textContent || ''), node);
          parent.normalize();
        });
      }

      function highlightPhrase() {
        clearHighlights();

        var root = document.querySelector('.site-main') || document.body;
        if (!root) {
          return false;
        }

        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
          acceptNode: function (node) {
            if (!node || !node.textContent || !node.textContent.trim()) {
              return NodeFilter.FILTER_REJECT;
            }

            var parentName = node.parentElement && node.parentElement.tagName;
            if (parentName === 'SCRIPT' || parentName === 'STYLE') {
              return NodeFilter.FILTER_REJECT;
            }

            return NodeFilter.FILTER_ACCEPT;
          },
        });

        var loweredPhrase = phrase.toLowerCase();
        var currentNode = walker.nextNode();
        while (currentNode) {
          var text = currentNode.textContent || '';
          var startIndex = text.toLowerCase().indexOf(loweredPhrase);

          if (startIndex !== -1) {
            var range = document.createRange();
            range.setStart(currentNode, startIndex);
            range.setEnd(currentNode, startIndex + phrase.length);

            var highlight = document.createElement('span');
            highlight.setAttribute('data-insights-search-highlight', '1');
            highlight.style.background = 'rgba(103, 151, 234, 0.38)';
            highlight.style.boxShadow = '0 0 0 6px rgba(103, 151, 234, 0.18)';
            highlight.style.borderRadius = '6px';
            highlight.style.transition = 'background 700ms ease, box-shadow 700ms ease';
            highlight.style.padding = '0 2px';

            try {
              range.surroundContents(highlight);
              highlight.scrollIntoView({ behavior: 'smooth', block: 'center' });

              window.setTimeout(function () {
                highlight.style.background = 'rgba(103, 151, 234, 0.12)';
                highlight.style.boxShadow = '0 0 0 0 rgba(103, 151, 234, 0)';
              }, 1400);

              window.setTimeout(function () {
                var parent = highlight.parentNode;
                if (!parent) {
                  return;
                }

                parent.replaceChild(document.createTextNode(highlight.textContent || ''), highlight);
                parent.normalize();
              }, 2600);
              return true;
            } catch (error) {
              return false;
            }
          }

          currentNode = walker.nextNode();
        }

        return false;
      }

      window.setTimeout(highlightPhrase, 120);
      return true;
    })();
    true;
  `;
}

function buildDashboardFocusScript(target: MobileDashboardFocusTarget) {
  return `
    (function () {
      var target = ${JSON.stringify(target)};
      var maxAttempts = 18;
      var attemptCount = 0;

      function getHeaderOffset() {
        var header = document.querySelector('.site-header');
        if (!header) {
          return 24;
        }

        return Math.max(16, Math.round(header.getBoundingClientRect().height || 0) + 12);
      }

      function scrollToNode(node) {
        if (!node) {
          return;
        }

        var top = node.getBoundingClientRect().top + window.scrollY - getHeaderOffset();
        window.scrollTo({
          top: Math.max(0, top),
          behavior: 'smooth',
        });
      }

      function clearFocusHighlights() {
        document.querySelectorAll('[data-insights-focus-highlight="1"]').forEach(function (node) {
          node.style.transition = '';
          node.style.boxShadow = '';
          node.style.outline = '';
          node.style.outlineOffset = '';
          node.style.backgroundColor = '';
        });
      }

      function applyFocusHighlight(node) {
        if (!node) {
          return;
        }

        node.setAttribute('data-insights-focus-highlight', '1');
        node.style.transition = 'background-color 700ms ease, box-shadow 700ms ease, outline-color 700ms ease';
        node.style.backgroundColor = 'rgba(103, 151, 234, 0.12)';
        node.style.boxShadow = '0 0 0 6px rgba(103, 151, 234, 0.18)';
        node.style.outline = '2px solid rgba(103, 151, 234, 0.55)';
        node.style.outlineOffset = '4px';
      }

      function fadeFocusHighlight(node) {
        if (!node) {
          return;
        }

        node.style.backgroundColor = 'transparent';
        node.style.boxShadow = '0 0 0 0 rgba(103, 151, 234, 0)';
        node.style.outline = '2px solid rgba(103, 151, 234, 0)';
      }

      function focusBookingSection() {
        var bookingSection = document.getElementById('dashboard-booking-section');
        if (!bookingSection) {
          return false;
        }

        clearFocusHighlights();
        applyFocusHighlight(bookingSection);
        scrollToNode(bookingSection);
        window.setTimeout(function () {
          fadeFocusHighlight(bookingSection);
        }, 1400);
        return true;
      }

      function focusNewsletterSection() {
        var newsletterSection = document.getElementById('dashboard-newsletter-section');
        var checkboxRow = document.getElementById('dashboard-newsletter-checkbox-row');
        var checkbox = document.getElementById('id_subscribe_to_newsletter');
        if (!newsletterSection) {
          return false;
        }

        clearFocusHighlights();
        applyFocusHighlight(newsletterSection);
        applyFocusHighlight(checkboxRow);
        applyFocusHighlight(checkbox);
        scrollToNode(newsletterSection);

        if (checkbox && checkbox.checked) {
          window.ReactNativeWebView && window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'already-subscribed' }));
        }

        window.setTimeout(function () {
          fadeFocusHighlight(newsletterSection);
          fadeFocusHighlight(checkboxRow);
          fadeFocusHighlight(checkbox);
        }, 1400);
        return true;
      }

      function tryFocusTarget() {
        attemptCount += 1;

        var wasApplied = false;
        if (target === 'booking') {
          wasApplied = focusBookingSection();
        }

        if (target === 'newsletter') {
          wasApplied = focusNewsletterSection();
        }

        if (wasApplied || attemptCount >= maxAttempts) {
          return true;
        }

        window.setTimeout(tryFocusTarget, 180);
        return false;
      }

      window.setTimeout(tryFocusTarget, 180);

      return true;
    })();
    true;
  `;
}

export default function App() {
  const webViewRef = useRef<WebView>(null);
  const webLoaderTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const webLoaderStartedAtRef = useRef<number>(0);
  const pushRegistrationAttemptedRef = useRef(false);
  const pendingSearchHighlightRef = useRef<string | null>(null);
  const pendingDashboardFocusRef = useRef<MobileDashboardFocusTarget | null>(null);
  const drawerOffset = useRef(new Animated.Value(-DRAWER_WIDTH)).current;
  const searchSheetOpacity = useRef(new Animated.Value(0)).current;
  const searchSheetTranslate = useRef(new Animated.Value(18)).current;
  const nativeScreenTranslate = useRef(new Animated.Value(0)).current;
  const previousNativeScreenTranslate = useRef(new Animated.Value(0)).current;
  const previousNativeScreenOpacity = useRef(new Animated.Value(1)).current;
  const nativeScreenTransitionRef = useRef<Animated.CompositeAnimation | null>(null);
  const landingDataMotion = useRef(new Animated.Value(0)).current;
  const landingAnimationRef = useRef<Animated.CompositeAnimation | null>(null);
  const searchIndexRequestedRef = useRef(false);
  const [nativeScreen, setNativeScreen] = useState<NativeScreen>('landing');
  const [transitioningFromScreen, setTransitioningFromScreen] = useState<NativeAppScreen | null>(null);
  const [transitioningToScreen, setTransitioningToScreen] = useState<NativeAppScreen | null>(null);
  const [currentUrl, setCurrentUrl] = useState(buildRouteUrl('/'));
  const [currentTitle, setCurrentTitle] = useState('Insights');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pageReady, setPageReady] = useState(false);
  const [showWebLoader, setShowWebLoader] = useState(false);
  const [webError, setWebError] = useState<string | null>(null);
  const [searchSheetOpen, setSearchSheetOpen] = useState(false);
  const [searchSheetMounted, setSearchSheetMounted] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [keepSignedIn, setKeepSignedIn] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [recoveryEmail, setRecoveryEmail] = useState('');
  const [passwordResetEmail, setPasswordResetEmail] = useState('');
  const [expoPushToken, setExpoPushToken] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authNotice, setAuthNotice] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [keyboardHeight, setKeyboardHeight] = useState(0);
  const [searchContentIndex, setSearchContentIndex] = useState<SearchContentIndex>({});
  const shouldAnimateBrandIcon = nativeScreen === 'landing' || (nativeScreen === 'web' && !pageReady && !webError);
  const activeRoute = getRouteForUrl(currentUrl);
  const normalizedSearchQuery = searchQuery.trim().toLowerCase();
  const searchResults = SEARCH_ROUTES.map(function (route) {
    const pagePhrases = searchContentIndex[route.path] || [];
    const matchState = getRouteSearchMatches(route, normalizedSearchQuery, pagePhrases);

    return {
      route,
      matchesQuery: matchState.matchesQuery,
      matchedTerms: matchState.matchedTerms,
      score: matchState.score,
    };
  })
    .filter(function (result) {
      return result.matchesQuery;
    })
    .sort(function (left, right) {
      if (right.score !== left.score) {
        return right.score - left.score;
      }

      return left.route.label.localeCompare(right.route.label);
    });

  const searchSheetBottom = keyboardHeight > 0 ? keyboardHeight + 16 : 108;
  const searchSheetMaxHeight = keyboardHeight > 0 ? Math.max(220, SCREEN_HEIGHT - keyboardHeight - 120) : SCREEN_HEIGHT * 0.56;

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

  useEffect(() => {
    let isActive = true;

    AsyncStorage.getItem(REMEMBERED_PORTAL_LAUNCH_KEY)
      .then(function (storedValue) {
        if (!isActive || storedValue !== 'true') {
          return;
        }

        resetAuthFeedback();
        setOtpCode('');
        openWebRoute('/dashboard/');
      })
      .catch(function () {
        return null;
      });

    return function () {
      isActive = false;
    };
  }, []);

  useEffect(() => {
    async function buildSearchContentIndex() {
      if (searchIndexRequestedRef.current) {
        return;
      }

      searchIndexRequestedRef.current = true;

      const entries = await Promise.all(
        SEARCH_ROUTES.map(async function (route) {
          try {
            const response = await fetch(buildRouteUrl(route.path), {
              method: 'GET',
              headers: {
                Accept: 'text/html,application/xhtml+xml',
              },
            });

            const responseUrl = response.url || buildRouteUrl(route.path);
            const responsePath = new URL(responseUrl, BASE_URL).pathname;
            if (!response.ok || responsePath.startsWith('/login/')) {
              return [route.path, []] as const;
            }

            const html = await response.text();
            return [route.path, extractSearchPhrasesFromHtml(html)] as const;
          } catch {
            return [route.path, []] as const;
          }
        })
      );

      setSearchContentIndex(
        entries.reduce<SearchContentIndex>(function (accumulator, [path, phrases]) {
          if (phrases.length > 0) {
            accumulator[path] = [...phrases];
          }
          return accumulator;
        }, {})
      );
    }

    void buildSearchContentIndex();
  }, []);

  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';

    const showSubscription = Keyboard.addListener(showEvent, function (event) {
      setKeyboardHeight(event.endCoordinates?.height || 0);
    });

    const hideSubscription = Keyboard.addListener(hideEvent, function () {
      setKeyboardHeight(0);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  useEffect(() => {
    function openNotificationRoute(routePath: string) {
      openWebRoute(routePath || '/dashboard/');
    }

    function handleNotificationResponse(response: Notifications.NotificationResponse | null) {
      if (!response) {
        return;
      }

      const routePath = response?.notification?.request?.content?.data?.routePath;
      openNotificationRoute(typeof routePath === 'string' ? routePath : '/dashboard/');
    }

    Notifications.getLastNotificationResponseAsync()
      .then(handleNotificationResponse)
      .catch(function () {
        return null;
      });

    const subscription = Notifications.addNotificationResponseReceivedListener(handleNotificationResponse);

    return () => {
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (nativeScreen !== 'web' || pushRegistrationAttemptedRef.current) {
      return;
    }
    pushRegistrationAttemptedRef.current = true;
    ensurePushNotifications({ promptIfNeeded: true, showResultAlert: false }).catch(function () {
      return null;
    });
  }, [nativeScreen]);

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
    setSearchSheetMounted(true);
    setSearchSheetOpen(true);
    searchSheetOpacity.stopAnimation();
    searchSheetTranslate.stopAnimation();
    searchSheetOpacity.setValue(0);
    searchSheetTranslate.setValue(18);
    Animated.parallel([
      Animated.timing(searchSheetOpacity, {
        toValue: 1,
        duration: SEARCH_SHEET_ANIMATION_DURATION_MS,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(searchSheetTranslate, {
        toValue: 0,
        duration: SEARCH_SHEET_ANIMATION_DURATION_MS,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
    ]).start();
  }

  function closeSearchSheet() {
    if (!searchSheetMounted) {
      setSearchSheetOpen(false);
      setSearchQuery('');
      return;
    }

    setSearchSheetOpen(false);
    searchSheetOpacity.stopAnimation();
    searchSheetTranslate.stopAnimation();
    Animated.parallel([
      Animated.timing(searchSheetOpacity, {
        toValue: 0,
        duration: SEARCH_SHEET_ANIMATION_DURATION_MS,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(searchSheetTranslate, {
        toValue: 18,
        duration: SEARCH_SHEET_ANIMATION_DURATION_MS,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }),
    ]).start(function () {
      setSearchSheetMounted(false);
      setSearchQuery('');
    });
  }

  async function setPortalResumePreference(shouldResume: boolean) {
    try {
      if (shouldResume) {
        await AsyncStorage.setItem(REMEMBERED_PORTAL_LAUNCH_KEY, 'true');
        return;
      }

      await AsyncStorage.removeItem(REMEMBERED_PORTAL_LAUNCH_KEY);
    } catch {
      // Ignore storage failures and fall back to non-persistent launch behavior.
    }
  }

  function injectHighlightedSearchPhrase(phrase: string) {
    if (!phrase.trim()) {
      return;
    }

    webViewRef.current?.injectJavaScript(buildSearchHighlightScript(phrase.trim()));
  }

  function injectDashboardFocusTarget(target: MobileDashboardFocusTarget) {
    webViewRef.current?.injectJavaScript(buildDashboardFocusScript(target));
  }

  function openRouteWithDashboardFocus(path: string, target: MobileDashboardFocusTarget) {
    const currentPath = getRouteForUrl(currentUrl)?.path;
    pendingDashboardFocusRef.current = target;
    openRoute(path);

    if (nativeScreen === 'web' && currentPath === path && pageReady) {
      setTimeout(function () {
        injectDashboardFocusTarget(target);
        pendingDashboardFocusRef.current = null;
      }, SEARCH_SHEET_ANIMATION_DURATION_MS + 40);
    }
  }

  function openRoute(path: string, highlightPhrase?: string) {
    const nextUrl = buildRouteUrl(path);
    const nextRoute = [...BOTTOM_NAV_ROUTES, ...DRAWER_ROUTES].find((route) => route.path === path);
    const currentPath = getRouteForUrl(currentUrl)?.path;
    const normalizedHighlightPhrase = highlightPhrase?.trim() || '';

    pendingSearchHighlightRef.current = normalizedHighlightPhrase || null;
    setCurrentUrl(nextUrl);
    setCurrentTitle(nextRoute?.label || getRouteForUrl(nextUrl)?.label || 'Insights');
    setWebError(null);
    closeDrawer();
    closeSearchSheet();

    if (normalizedHighlightPhrase && nativeScreen === 'web' && currentPath === path && pageReady) {
      setTimeout(function () {
        injectHighlightedSearchPhrase(normalizedHighlightPhrase);
        pendingSearchHighlightRef.current = null;
      }, SEARCH_SHEET_ANIMATION_DURATION_MS + 40);
    }
  }

  function openWebRoute(path: string) {
    const nextUrl = buildRouteUrl(path);
    setCurrentUrl(nextUrl);
    setCurrentTitle(getRouteForUrl(nextUrl)?.label || 'Client Portal');
    setWebError(null);
    beginWebLoader();
    closeDrawer();
    closeSearchSheet();
    setNativeScreen('web');
  }

  function syncPushTokenWithWebSession(token: string, action: 'register' | 'unregister' = 'register') {
    const normalizedToken = String(token || '').trim();
    if (!normalizedToken) {
      return;
    }

    const deviceName = (Device.modelName || '').trim();
    const syncUrl = buildRouteUrl(MOBILE_PUSH_DEVICE_PATH);
    webViewRef.current?.injectJavaScript(`
      (function () {
        fetch(${JSON.stringify(syncUrl)}, {
          method: 'POST',
          headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
          },
          credentials: 'same-origin',
          body: JSON.stringify({
            action: ${JSON.stringify(action)},
            token: ${JSON.stringify(normalizedToken)},
            platform: ${JSON.stringify(Platform.OS)},
            deviceName: ${JSON.stringify(deviceName)}
          })
        }).catch(function () {
          return null;
        });
        return true;
      })();
      true;
    `);
  }

  function completeMobileLogout() {
    void setPortalResumePreference(false);
    resetAuthFeedback();
    setUsername('');
    setPassword('');
    setOtpCode('');
    setRecoveryEmail('');
    setPasswordResetEmail('');
    setCurrentUrl(buildRouteUrl('/'));
    setCurrentTitle('Insights');
    setWebError(null);
    setPageReady(false);
    setShowWebLoader(false);
    closeDrawer();
    closeSearchSheet();
    setNativeScreen('landing');
  }

  function performLogoutFromMobileApp() {
    closeDrawer();
    closeSearchSheet();
    webViewRef.current?.injectJavaScript(`
      (function () {
        var logoutForm = document.querySelector('form[action*="/logout/"]');
        var mobilePushToken = ${JSON.stringify(expoPushToken)};
        var pushSyncUrl = ${JSON.stringify(buildRouteUrl(MOBILE_PUSH_DEVICE_PATH))};
        if (!logoutForm) {
          window.ReactNativeWebView && window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'logout-missing-form' }));
          return true;
        }

        var unregisterPromise = mobilePushToken
          ? fetch(pushSyncUrl, {
              method: 'POST',
              headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
              },
              credentials: 'same-origin',
              body: JSON.stringify({
                action: 'unregister',
                token: mobilePushToken,
                platform: ${JSON.stringify(Platform.OS)}
              })
            }).catch(function () {
              return null;
            })
          : Promise.resolve();

        unregisterPromise.then(function () {
          return fetch(logoutForm.action, {
            method: (logoutForm.method || 'POST').toUpperCase(),
            body: new FormData(logoutForm),
            credentials: 'same-origin'
          });
        })
        .then(function (response) {
          if (!response.ok) {
            throw new Error('logout-failed');
          }
          window.ReactNativeWebView && window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'logout-success' }));
        })
        .catch(function () {
          window.ReactNativeWebView && window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'logout-error' }));
        });

        return true;
      })();
      true;
    `);
  }

  function confirmLogoutFromMobileApp() {
    Alert.alert(
      'Log out?',
      'Do you want to log out of your Miranda Insights account on this device?',
      [
        {
          text: 'Cancel',
          style: 'cancel',
        },
        {
          text: 'Log Out',
          style: 'destructive',
          onPress: performLogoutFromMobileApp,
        },
      ]
    );
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
    await ensurePushNotifications({ promptIfNeeded: true, showResultAlert: true });
  }

  async function ensurePushNotifications(options?: {
    promptIfNeeded?: boolean;
    showResultAlert?: boolean;
  }) {
    try {
      if (!Device.isDevice) {
        if (options?.showResultAlert) {
          Alert.alert('Notifications unavailable', 'Push notifications require a physical mobile device.');
        }
        return null;
      }

      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('default', {
          name: 'default',
          importance: Notifications.AndroidImportance.HIGH,
          sound: 'default',
        });
      }

      let permission = await Notifications.getPermissionsAsync();
      if (!permission.granted && options?.promptIfNeeded !== false) {
        permission = await Notifications.requestPermissionsAsync();
      }

      if (!permission.granted) {
        if (options?.showResultAlert) {
          Alert.alert('Notifications not enabled', 'Notification permission was not granted on this device.');
        }
        return null;
      }

      let tokenResponse: Notifications.ExpoPushToken;
      try {
        tokenResponse = EXPO_PUSH_PROJECT_ID
          ? await Notifications.getExpoPushTokenAsync({ projectId: EXPO_PUSH_PROJECT_ID })
          : await Notifications.getExpoPushTokenAsync();
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : '';
        const isMissingProjectId = !EXPO_PUSH_PROJECT_ID && /project.?id/i.test(errorMessage);
        if (options?.showResultAlert) {
          Alert.alert(
            'Notifications unavailable',
            isMissingProjectId
              ? 'Set EXPO_PUBLIC_EXPO_PROJECT_ID in mobile_app/.env, then restart Expo and try again.'
              : 'Notification permissions were granted, but Expo push registration could not be completed.'
          );
        }
        return null;
      }

      const nextToken = tokenResponse.data;
      setExpoPushToken(nextToken);
      if (nativeScreen === 'web') {
        syncPushTokenWithWebSession(nextToken, 'register');
      }

      if (options?.showResultAlert) {
        Alert.alert('Notifications enabled', 'Push notifications are ready for project messages and project updates.');
      }

      return nextToken;
    } catch (error) {
      if (options?.showResultAlert) {
        Alert.alert('Notifications unavailable', 'Notification permissions or push registration could not be completed in this session.');
      }
      return null;
    }
  }

  function reloadPage() {
    setWebError(null);
    beginWebLoader();
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
        rememberMe: keepSignedIn ? 'true' : '',
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

      void setPortalResumePreference(keepSignedIn);
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
        rememberMe: keepSignedIn ? 'true' : '',
      });

      if (!data.ok || !data.sessionUrl) {
        setAuthError(data.message || 'Unable to verify your code.');
        applyFieldErrors(data.fieldErrors);
        return;
      }

      void setPortalResumePreference(keepSignedIn);
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
    if (expoPushToken) {
      syncPushTokenWithWebSession(expoPushToken, 'register');
    }
    if (pendingSearchHighlightRef.current) {
      injectHighlightedSearchPhrase(pendingSearchHighlightRef.current);
      pendingSearchHighlightRef.current = null;
    }
    if (pendingDashboardFocusRef.current && getRouteForUrl(currentUrl)?.path === '/dashboard/') {
      injectDashboardFocusTarget(pendingDashboardFocusRef.current);
      pendingDashboardFocusRef.current = null;
    }
  }

  function handleNavigationStateChange(navigationState: {
    url: string;
    title?: string | null;
    canGoBack: boolean;
  }) {
    const authScreen = getNativeAuthScreenForPath(new URL(navigationState.url, BASE_URL).pathname);
    if (authScreen) {
      void setPortalResumePreference(false);
      resetAuthFeedback();
      setOtpCode('');
      closeDrawer();
      closeSearchSheet();
      setNativeScreen(authScreen);
      setCurrentTitle('Insights');
      setWebError(null);
      setPageReady(false);
      setShowWebLoader(false);
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
    method?: string;
    navigationType?: 'click' | 'formsubmit' | 'backforward' | 'reload' | 'formresubmit' | 'other';
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
      const requestMethod = String(request.method || 'GET').trim().toUpperCase();
      const isFormSubmission = request.navigationType === 'formsubmit' || request.navigationType === 'formresubmit' || requestMethod !== 'GET';

      if (isFormSubmission) {
        return true;
      }

      try {
        const requestUrl = new URL(request.url);
        const authScreen = getNativeAuthScreenForPath(requestUrl.pathname);
        if (authScreen) {
          void setPortalResumePreference(false);
          resetAuthFeedback();
          setOtpCode('');
          closeDrawer();
          closeSearchSheet();
          setCurrentTitle('Insights');
          setWebError(null);
          setPageReady(false);
          setShowWebLoader(false);
          setNativeScreen(authScreen);
          return false;
        }

        const mobileFocus = requestUrl.searchParams.get('mobile_focus');
        if (requestUrl.pathname === '/dashboard/' && (mobileFocus === 'booking' || mobileFocus === 'newsletter')) {
          openRouteWithDashboardFocus('/dashboard/', mobileFocus);
          return false;
        }
      } catch {
        // Fall through to default in-app routing.
      }

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

  function renderLogoutIcon() {
    return <Ionicons color="#f8fafc" name="log-out-outline" size={20} />;
  }

  function renderRefreshIcon() {
    return <Ionicons color="#f8fafc" name="refresh-outline" size={20} />;
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

  function renderSearchKeywords(route: AppRoute, matches: SearchMatch[]) {
    return (
      <View style={styles.searchSheetKeywordsWrap}>
        {matches.map(function (match, index) {
          return (
            <Pressable key={`${route.key}-${match.targetText}-${index}`} onPress={() => openRoute(route.path, match.targetText)} style={styles.searchSheetKeywordChip}>
              <Text style={styles.searchSheetKeywordText}>{match.text}</Text>
            </Pressable>
          );
        })}
      </View>
    );
  }

  function renderSearchSheet() {
    if (!searchSheetMounted) {
      return null;
    }

    return (
      <>
        <Animated.View pointerEvents={searchSheetOpen ? 'auto' : 'none'} style={[styles.searchSheetBackdrop, { opacity: searchSheetOpacity }]}> 
          <Pressable onPress={closeSearchSheet} style={styles.searchSheetBackdropPressable} />
        </Animated.View>
        <Animated.View
          style={[
            styles.searchSheet,
            {
              bottom: searchSheetBottom,
              maxHeight: searchSheetMaxHeight,
              opacity: searchSheetOpacity,
              transform: [{ translateY: searchSheetTranslate }],
            },
          ]}
        >
          <Text style={styles.searchSheetTitle}>Search Navigation</Text>
          <TextInput
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder="Search by keyword"
            placeholderTextColor="#90a3b9"
            style={styles.searchSheetInput}
            autoCapitalize="none"
            autoCorrect={false}
          />

          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.searchSheetResults}>
            {searchResults.map(({ route, matchedTerms }) => (
              <View key={route.key} style={styles.searchSheetLink}>
                <Pressable onPress={() => openRoute(route.path, matchedTerms[0]?.targetText)} style={styles.searchSheetRouteButton}>
                  <Text style={styles.searchSheetLinkText}>{route.label}</Text>
                </Pressable>
                {renderSearchKeywords(route, matchedTerms)}
              </View>
            ))}

            {searchResults.length === 0 ? <Text style={styles.searchSheetEmpty}>No matching pages.</Text> : null}
          </ScrollView>
        </Animated.View>
      </>
    );
  }

  function renderNativeLanding() {
    return renderAuthScreenLayout({
      eyebrow: 'Client Portal',
      title: 'Welcome to Miranda Insights',
      copy:
        "Log in to access your Miranda Insights client portal. New clients can book a consultation to get started.",
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
      copy: 'Miranda Insights clients can log in here to access their client portal, project updates, messages, and scheduling tools.',
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
          <Pressable onPress={() => setKeepSignedIn((currentValue) => !currentValue)} style={styles.authCheckboxRow}>
            <Ionicons color={keepSignedIn ? AUTH_ACCENT_COLOR : '#8ba2b9'} name={keepSignedIn ? 'checkbox' : 'square-outline'} size={20} />
            <View style={styles.authCheckboxTextWrap}>
              <Text style={styles.authCheckboxLabel}>Keep me signed in</Text>
              <Text style={styles.authCheckboxCopy}>Stay logged in on this device until you log out. Recommended to receive push notifications.</Text>
            </View>
          </Pressable>
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

              <View style={styles.headerActionGroup}>
                <Pressable onPress={reloadPage} style={styles.headerButton}>
                  {renderRefreshIcon()}
                </Pressable>

                <Pressable onPress={confirmLogoutFromMobileApp} style={styles.headerButton}>
                  {renderLogoutIcon()}
                </Pressable>
              </View>
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
                onMessage={(event) => {
                  try {
                    const payload = JSON.parse(event.nativeEvent.data);
                    if (payload?.type === 'logout-success') {
                      completeMobileLogout();
                      return;
                    }

                    if (payload?.type === 'logout-missing-form' || payload?.type === 'logout-error') {
                      Alert.alert('Logout unavailable', 'The logout action could not be completed from this screen.');
                      return;
                    }

                    if (payload?.type === 'already-subscribed') {
                      Alert.alert('Already subscribed', 'You are already subscribed to updates on this account.');
                    }
                  } catch {
                    // Ignore unrelated WebView messages.
                  }
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
                <Text style={styles.drawerTitle}>Menu</Text>
              </View>

              <View style={styles.drawerSection}>
                <Text style={styles.drawerSectionTitle}>Navigate</Text>
                {DRAWER_ROUTES.map((route) => (
                  <Pressable key={route.key} onPress={() => openRoute(route.path)} style={styles.drawerLinkRow}>
                    <Text style={styles.drawerLinkText}>{route.label}</Text>
                  </Pressable>
                ))}
              </View>

              <View style={[styles.drawerSection, styles.drawerSectionSeparated]}>
                <Text style={styles.drawerSectionTitle}>Other Actions</Text>
                <Pressable onPress={openCurrentPageExternally} style={styles.drawerLinkRow}>
                  <Text style={styles.drawerActionText}>Open in Default Browser</Text>
                </Pressable>
                <Pressable onPress={requestNotifications} style={styles.drawerLinkRow}>
                  <Text style={styles.drawerActionText}>Enable Notifications</Text>
                </Pressable>
              </View>

              <View style={styles.drawerFooter}>
                <View style={styles.drawerFooterRow}>
                  <Pressable onPress={confirmLogoutFromMobileApp} style={styles.drawerLogoutButton}>
                    <Ionicons color="#f8fafc" name="log-out-outline" size={18} />
                    <Text style={styles.drawerLogoutText}>Log Out</Text>
                  </Pressable>
                  <Image source={require('./assets/drawer-logo.png')} style={styles.drawerFooterLogo} />
                </View>
              </View>
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
  authCheckboxRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    paddingTop: 4,
  },
  authCheckboxTextWrap: {
    flex: 1,
    gap: 2,
  },
  authCheckboxLabel: {
    color: '#f8fafc',
    fontSize: 14,
    fontWeight: '700',
  },
  authCheckboxCopy: {
    color: '#8ba2b9',
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
  headerActionGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
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
    backgroundColor: '#0c111b',
  },
  webView: {
    flex: 1,
    backgroundColor: '#0c111b',
  },
  webViewHidden: {
    flex: 1,
    opacity: 0,
    backgroundColor: '#0c111b',
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
  searchSheetBackdropPressable: {
    ...StyleSheet.absoluteFillObject,
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
  searchSheetRouteButton: {
    alignSelf: 'flex-start',
  },
  searchSheetLinkText: {
    color: '#f8fafc',
    fontSize: 15,
    fontWeight: '700',
  },
  searchSheetKeywordsWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 4,
  },
  searchSheetKeywordChip: {
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
    backgroundColor: 'rgba(103, 151, 234, 0.16)',
    borderWidth: 1,
    borderColor: 'rgba(103, 151, 234, 0.26)',
  },
  searchSheetKeywordText: {
    color: '#d9e7fb',
    fontSize: 12,
    fontWeight: '600',
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
    flexGrow: 1,
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
  drawerSectionSeparated: {
    marginTop: 14,
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
  drawerFooter: {
    marginTop: 'auto',
    paddingTop: 10,
  },
  drawerFooterRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  drawerLogoutButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: 'rgba(150, 180, 220, 0.2)',
    backgroundColor: 'rgba(17, 35, 58, 0.9)',
  },
  drawerLogoutText: {
    color: '#f8fafc',
    fontSize: 14,
    fontWeight: '700',
  },
  drawerFooterLogo: {
    width: 48,
    height: 48,
    borderRadius: 24,
  },
});
