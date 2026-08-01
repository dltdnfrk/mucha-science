import { describe, expect, it } from "vitest";
import packageJson from "../../package.json";

describe("Mucha Science web product identity", () => {
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
});
