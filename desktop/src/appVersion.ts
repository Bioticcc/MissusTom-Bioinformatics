export const APP_VERSION = "0.3.0-rc.26";
export const DEVELOPMENT_BUILD_REVISION = "development";
export const BUILD_REVISION =
  (import.meta.env.VITE_BUILD_REVISION ?? "").trim() || DEVELOPMENT_BUILD_REVISION;

export function formatBuildLabel(version: string, revision: string | undefined): string {
  const value = (revision ?? DEVELOPMENT_BUILD_REVISION).trim() || DEVELOPMENT_BUILD_REVISION;
  const short =
    value === DEVELOPMENT_BUILD_REVISION || value.length < 8 ? value : value.slice(0, 7);
  return `v${version} (${short})`;
}
