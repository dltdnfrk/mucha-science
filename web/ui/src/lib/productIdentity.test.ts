import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import packageJson from "../../package.json";

interface WebAppManifest {
  readonly icons: ReadonlyArray<{
    readonly purpose: string;
    readonly sizes: string;
    readonly src: string;
    readonly type: string;
  }>;
  readonly name: string;
  readonly short_name: string;
}

describe("MUNI lab web product identity", () => {
  it("uses a standalone web package with the copied UI toolchain", () => {
    expect(packageJson.name).toBe("mucha-science-web-ui");
    expect(packageJson.private).toBe(true);
    expect(packageJson.scripts.build).toBe("tsc -b && vite build");
    expect(packageJson.dependencies.react).toBeDefined();
  });

  it("does not ship desktop shell packages", () => {
    const packages = {
      ...packageJson.dependencies,
      ...packageJson.devDependencies,
    };
    expect(Object.keys(packages).some((name) => name.startsWith("@tauri"))).toBe(false);
  });

  it("publishes one installable MUNI lab identity and icon", () => {
    const indexHtml = readFileSync(new URL("../../index.html", import.meta.url), "utf8");
    const manifest = JSON.parse(
      readFileSync(new URL("../../public/manifest.webmanifest", import.meta.url), "utf8"),
    ) as WebAppManifest;

    expect(indexHtml).toContain("<title>MUNI lab</title>");
    expect(indexHtml).toContain('rel="manifest" href="/manifest.webmanifest"');
    expect(indexHtml).toContain('rel="icon" type="image/png" sizes="32x32"');
    expect(indexHtml).toContain('rel="apple-touch-icon" sizes="180x180"');
    expect(indexHtml).not.toContain("Muchanipo");
    expect(manifest.name).toBe("MUNI lab");
    expect(manifest.short_name).toBe("MUNI lab");
    expect(manifest.icons).toEqual([
      {
        src: "/muni-lab-icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/muni-lab-icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any maskable",
      },
      {
        src: "/muni-lab-icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
    ]);
  });
});
