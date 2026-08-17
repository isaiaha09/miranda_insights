import { NativeModules, Platform } from 'react-native';

export type AppRoute = {
  key: string;
  label: string;
  path: string;
  keywords: string[];
};

export const MOBILE_APP_QUERY_KEY = 'mobile_app';
export const MOBILE_APP_QUERY_VALUE = '1';

const configuredBaseUrl = (process.env.EXPO_PUBLIC_INSIGHTS_SITE_URL || '').trim();
export const EXPO_PUSH_PROJECT_ID = (process.env.EXPO_PUBLIC_EXPO_PROJECT_ID || '').trim();

function isLoopbackHostname(hostname: string) {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '0.0.0.0';
}

function getMetroHostname() {
  const sourceCode = NativeModules.SourceCode as { scriptURL?: string } | undefined;
  const scriptUrl = sourceCode?.scriptURL;

  if (!scriptUrl) {
    return '';
  }

  try {
    return new URL(scriptUrl).hostname;
  } catch {
    const match = scriptUrl.match(/^https?:\/\/([^/:]+)/i);
    return match ? match[1] : '';
  }
}

function getDefaultBaseUrl() {
  const metroHostname = getMetroHostname();

  if (metroHostname && !isLoopbackHostname(metroHostname)) {
    return `http://${metroHostname}:8000`;
  }

  return Platform.select({
    android: 'http://10.0.2.2:8000',
    ios: 'http://127.0.0.1:8000',
    default: 'http://127.0.0.1:8000',
  }) as string;
}

export const DEFAULT_BASE_URL = getDefaultBaseUrl();

function normalizeBaseUrl(value: string) {
  return value.replace(/\/+$/, '');
}

function resolveBaseUrl() {
  const metroHostname = getMetroHostname();

  if (!configuredBaseUrl) {
    return DEFAULT_BASE_URL;
  }

  try {
    const configuredUrl = new URL(normalizeBaseUrl(configuredBaseUrl));

    if (metroHostname && !isLoopbackHostname(metroHostname) && isLoopbackHostname(configuredUrl.hostname)) {
      configuredUrl.hostname = metroHostname;
      return configuredUrl.toString().replace(/\/+$/, '');
    }

    return configuredUrl.toString().replace(/\/+$/, '');
  } catch {
    return normalizeBaseUrl(configuredBaseUrl);
  }
}

export const BASE_URL = resolveBaseUrl();
export const BASE_URL_LABEL = BASE_URL.replace(/^https?:\/\//, '');

export const PRIMARY_ROUTES: AppRoute[] = [
  {
    key: 'about',
    label: 'About',
    path: '/about/',
    keywords: ['company', 'team', 'story', 'mission', 'founder', 'values'],
  },
  {
    key: 'partnerships',
    label: 'Partnerships',
    path: '/operational-partnership/',
    keywords: ['ongoing support', 'accountability', 'collaboration', 'guidance', 'growth'],
  },
  {
    key: 'services',
    label: 'Services',
    path: '/services/',
    keywords: ['operational services', 'projects', 'consulting', 'systems', 'analysis', 'solutions'],
  },
  {
    key: 'individual-services',
    label: 'Individual Support',
    path: '/individual-services/',
    keywords: ['tutoring', 'fitness coaching', 'mentorship', 'accountability', 'personal goals'],
  },
  {
    key: 'resources',
    label: 'Resources',
    path: '/contact/',
    keywords: ['contact', 'email', 'message', 'support', 'questions', 'client process'],
  },
  {
    key: 'dashboard',
    label: 'Client Portal',
    path: '/dashboard/',
    keywords: ['portal', 'overview', 'account', 'projects', 'updates', 'activity'],
  },
];

export const BOTTOM_NAV_ROUTES: AppRoute[] = [
  PRIMARY_ROUTES[5],
  PRIMARY_ROUTES[2],
  PRIMARY_ROUTES[3],
  PRIMARY_ROUTES[4],
];

export const DRAWER_ROUTES: AppRoute[] = [
  ...PRIMARY_ROUTES,
];

export const LEGAL_ROUTES: AppRoute[] = [
  {
    key: 'privacy',
    label: 'Privacy Policy',
    path: '/privacy/',
    keywords: ['privacy', 'policy', 'data', 'collection', 'security', 'information'],
  },
  {
    key: 'terms',
    label: 'Terms of Service',
    path: '/terms/',
    keywords: ['terms', 'service', 'agreement', 'legal', 'rules', 'conditions'],
  },
];

export const SEARCH_ROUTES: AppRoute[] = Array.from(
  new Map([...DRAWER_ROUTES, ...LEGAL_ROUTES, ...BOTTOM_NAV_ROUTES].map((route) => [route.path, route])).values()
);

export function markMobileAppUrl(url: string) {
  try {
    const base = new URL(BASE_URL);
    const nextUrl = new URL(url, BASE_URL);

    if (nextUrl.origin !== base.origin) {
      return url;
    }

    nextUrl.searchParams.set(MOBILE_APP_QUERY_KEY, MOBILE_APP_QUERY_VALUE);
    return nextUrl.toString();
  } catch {
    return url;
  }
}

export function buildRouteUrl(path: string) {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return markMobileAppUrl(path);
  }

  return markMobileAppUrl(`${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`);
}

export function getRouteForUrl(url: string) {
  let pathname = '/';

  try {
    pathname = new URL(url, BASE_URL).pathname || '/';
  } catch {
    pathname = '/';
  }

  const sortedRoutes = [...DRAWER_ROUTES, ...LEGAL_ROUTES, ...BOTTOM_NAV_ROUTES].sort(function (left, right) {
    return right.path.length - left.path.length;
  });

  return sortedRoutes.find(function (route) {
    if (route.path === '/') {
      return pathname === '/';
    }

    return pathname.startsWith(route.path);
  });
}
