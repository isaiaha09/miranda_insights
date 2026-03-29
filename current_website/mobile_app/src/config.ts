import { NativeModules, Platform } from 'react-native';

export type AppRoute = {
  key: string;
  label: string;
  path: string;
};

export const MOBILE_APP_QUERY_KEY = 'mobile_app';
export const MOBILE_APP_QUERY_VALUE = '1';

const configuredBaseUrl = (process.env.EXPO_PUBLIC_INSIGHTS_SITE_URL || '').trim();

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

  if (metroHostname && metroHostname !== 'localhost' && metroHostname !== '127.0.0.1') {
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

export const BASE_URL = normalizeBaseUrl(configuredBaseUrl || DEFAULT_BASE_URL);
export const BASE_URL_LABEL = BASE_URL.replace(/^https?:\/\//, '');

export const PRIMARY_ROUTES: AppRoute[] = [
  { key: 'dashboard', label: 'Dashboard', path: '/dashboard/' },
  { key: 'services', label: 'Services', path: '/services/' },
  { key: 'products', label: 'Products', path: '/products/' },
];

export const BOTTOM_NAV_ROUTES: AppRoute[] = [
  { key: 'dashboard', label: 'Dashboard', path: '/dashboard/' },
  { key: 'products', label: 'Products', path: '/products/' },
  { key: 'services', label: 'Services', path: '/services/' },
  { key: 'contact', label: 'Contact', path: '/contact/' },
];

export const DRAWER_ROUTES: AppRoute[] = [
  ...PRIMARY_ROUTES,
  { key: 'about', label: 'About', path: '/about/' },
  { key: 'faq', label: 'FAQ', path: '/faq/' },
  { key: 'contact', label: 'Contact', path: '/contact/' },
];

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

  const sortedRoutes = [...DRAWER_ROUTES, ...BOTTOM_NAV_ROUTES].sort(function (left, right) {
    return right.path.length - left.path.length;
  });

  return sortedRoutes.find(function (route) {
    if (route.path === '/') {
      return pathname === '/';
    }

    return pathname.startsWith(route.path);
  });
}