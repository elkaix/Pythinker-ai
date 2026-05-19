import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { FileReferenceChip, isLikelyFilePath } from "@/components/FileReferenceChip";

describe("isLikelyFilePath", () => {
  it("accepts directory-shaped paths with file extensions", () => {
    expect(isLikelyFilePath("pythinker/agent/loop.py")).toBe(true);
    expect(isLikelyFilePath("webui/src/components/MarkdownTextRenderer.tsx")).toBe(true);
    expect(isLikelyFilePath("./scripts/webui_hash.py")).toBe(true);
    expect(isLikelyFilePath("/etc/hosts.conf")).toBe(true);
    expect(isLikelyFilePath("docs\\image-generation.md")).toBe(true);
  });

  it("accepts well-known bare filenames", () => {
    expect(isLikelyFilePath("Dockerfile")).toBe(true);
    expect(isLikelyFilePath("Makefile")).toBe(true);
    expect(isLikelyFilePath("README")).toBe(true);
    expect(isLikelyFilePath("package-lock.json")).toBe(true);
  });

  it("rejects URLs and protocol-prefixed strings", () => {
    expect(isLikelyFilePath("https://example.com/index.html")).toBe(false);
    expect(isLikelyFilePath("file:///home/user/foo.py")).toBe(false);
    expect(isLikelyFilePath("git+ssh://repo/path.git")).toBe(false);
  });

  it("rejects bare words without slashes or known special names", () => {
    expect(isLikelyFilePath("foo")).toBe(false);
    expect(isLikelyFilePath("foo.bar")).toBe(false);
    expect(isLikelyFilePath("")).toBe(false);
    expect(isLikelyFilePath("multi\nline/file.py")).toBe(false);
  });

  it("rejects relative ./ and ../ alone", () => {
    expect(isLikelyFilePath("./")).toBe(false);
    expect(isLikelyFilePath("../")).toBe(false);
  });
});

describe("FileReferenceChip", () => {
  it("renders the file basename by default", () => {
    render(<FileReferenceChip path="pythinker/agent/loop.py" />);
    const chip = screen.getByTestId("inline-file-path");
    expect(chip).toHaveTextContent("loop.py");
    expect(chip.getAttribute("aria-label")).toBe("pythinker/agent/loop.py");
  });

  it("renders the full path when display='path'", () => {
    render(<FileReferenceChip path="pythinker/agent/loop.py" display="path" />);
    const chip = screen.getByTestId("inline-file-path");
    expect(chip.textContent).toContain("pythinker/agent/");
    expect(chip.textContent).toContain("loop.py");
  });
});
