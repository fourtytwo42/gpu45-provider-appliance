import packageJson from "../../package.json";

export type ApplianceVersion = {
  version: string;
  commit: string;
  releasedAt: string | null;
};

export function getApplianceVersion(): ApplianceVersion {
  return {
    version: packageJson.version,
    commit: process.env.GPU45_RELEASE_COMMIT?.trim() || "development",
    releasedAt: process.env.GPU45_RELEASED_AT?.trim() || null,
  };
}
