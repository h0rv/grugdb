// Files are a path-to-text object or an array of {path, content} records.
export function fileEntries(files) {
  const entries = Array.isArray(files)
    ? files.map(({ path, content }) => [path, content])
    : Object.entries(files ?? {});
  const seen = new Set();
  return entries.map(([path, content]) => {
    if (typeof path !== "string" || typeof content !== "string") {
      throw new TypeError("Files must have a string path and content.");
    }
    const relative = path.replace(/^\/workspace\//, "");
    if (!relative || relative.startsWith("/") || relative.includes("\\")
        || relative.split("/").some((part) => !part || part === "." || part === "..")
        || /[\x00-\x1f]/.test(relative) || seen.has(relative)) {
      throw new Error(`Invalid or duplicate workspace path: ${path}`);
    }
    seen.add(relative);
    return { path, relative, content };
  });
}
