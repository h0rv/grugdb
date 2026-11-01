// Create with { type: "module" }, once per Run. Pyodide 314 rejects classic workers.
// Runtime files must live beside the supplied local pyodide.mjs.
const OUTPUT_LIMIT = 64 * 1024;
const DETAIL_LIMIT = 16 * 1024;
const TRUNCATED = "\n[output truncated]";
const DETAIL_TRUNCATED = "\n[detail truncated]";

function boundedDetail(text) {
  if (text.length <= DETAIL_LIMIT) return text;
  return text.slice(0, DETAIL_LIMIT - DETAIL_TRUNCATED.length) + DETAIL_TRUNCATED;
}

// Keep the runner separate from the submitted modules and never patch their code.
const RUN_TESTS = String.raw`
import json
import sys
import traceback
import unittest


def run_tests(selectors, detail_limit):
    marker = "\n[detail truncated]"

    def bounded(text):
        if len(text) <= detail_limit:
            return text
        return text[:detail_limit - len(marker)] + marker

    def exception_detail(error):
        parts = []
        remaining = detail_limit
        for part in traceback.TracebackException(*error).format():
            parts.append(part[:remaining])
            remaining -= len(part)
            if remaining < 0:
                return bounded("".join(parts) + marker)
        return "".join(parts)

    class Result(unittest.TestResult):
        def __init__(self):
            super().__init__()
            self.records = []
            self.active = None
            self.active_test = None

        def record(self, test, status, detail=""):
            if self.active is None:
                entry = {"id": bounded(test.id()), "status": None, "detail": ""}
                self.records.append(entry)
            else:
                entry = self.active
            rank = {None: -1, "passed": 0, "skipped": 1, "failed": 2, "error": 3}
            if rank[status] > rank[entry["status"]]:
                entry["status"] = status
            if detail:
                separator = "\n\n" if entry["detail"] else ""
                entry["detail"] = bounded(entry["detail"] + separator + detail)

        def startTest(self, test):
            super().startTest(test)
            self.active_test = test
            self.active = {"id": bounded(test.id()), "status": None, "detail": ""}
            self.records.append(self.active)

        def stopTest(self, test):
            if self.active["status"] is None:
                self.record(test, "error", "Test ended without reporting an outcome.")
            self.active = None
            self.active_test = None
            super().stopTest(test)

        def _exc_info_to_string(self, error, test):
            # TestResult also stores tracebacks. Bound those, not just the JSON.
            return exception_detail(error)

        def addSuccess(self, test):
            super().addSuccess(test)
            self.record(test, "passed")

        def addFailure(self, test, error):
            super().addFailure(test, error)
            self.record(test, "failed", self.failures[-1][1])

        def addError(self, test, error):
            super().addError(test, error)
            self.record(test, "error", self.errors[-1][1])

        def addSkip(self, test, reason):
            reason = bounded(str(reason))
            super().addSkip(test, reason)
            if self.active_test is not None and test is not self.active_test:
                reason = bounded(test.id()) + "\n" + reason
            self.record(test, "skipped", reason)

        def addExpectedFailure(self, test, error):
            super().addExpectedFailure(test, error)
            self.record(test, "skipped", "Expected failure:\n" + self.expectedFailures[-1][1])

        def addUnexpectedSuccess(self, test):
            super().addUnexpectedSuccess(test)
            self.record(test, "failed", "Unexpected success (marked expectedFailure).")

        def addSubTest(self, test, subtest, error):
            super().addSubTest(test, subtest, error)
            if error is not None:
                failed = issubclass(error[0], test.failureException)
                detail = (self.failures if failed else self.errors)[-1][1]
                self.record(test, "failed" if failed else "error",
                            bounded(subtest.id()) + "\n" + detail)

    result = Result()
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for selector in selectors:
        try:
            suite.addTests(loader.loadTestsFromName(selector))
        except BaseException:
            # Includes import-time SystemExit and invalid selectors. Other tests
            # still run, just as they do for unittest's synthetic import errors.
            result.records.append({"id": bounded(selector), "status": "error",
                                   "detail": exception_detail(sys.exc_info())})
    result.startTestRun()
    try:
        suite.run(result)
    except BaseException:
        result.records.append({"id": "<test run>", "status": "error",
                               "detail": exception_detail(sys.exc_info())})
    finally:
        result.stopTestRun()
        # Include writes without a trailing newline, on both streams.
        sys.stdout.flush()
        sys.stderr.flush()
    return json.dumps(result.records)


if sys.version_info < (3, 14):
    raise RuntimeError("grugdb needs Python 3.14 or newer (including annotationlib).")
import annotationlib
sys.path[:0] = ["/workspace/src", "/workspace"]
run_tests(json.loads(_worker_selectors), _worker_detail_limit)
`;

function validateRequest(data) {
  if (!data || typeof data !== "object") {
    throw new Error("Expected a worker run request.");
  }
  if (typeof data.runtimeURL !== "string" || !data.runtimeURL.trim()) {
    throw new Error("runtimeURL must point to a local pyodide.mjs.");
  }
  if (!data.files || typeof data.files !== "object" || Array.isArray(data.files)) {
    throw new Error("files must map project-relative paths to Python source.");
  }
  for (const [path, source] of Object.entries(data.files)) {
    if (
      typeof source !== "string" ||
      path.includes("\\") ||
      path.includes("\0") ||
      path.split("/").some((part) => !part || part === "." || part === "..")
    ) {
      throw new Error(`Invalid project file path or source: ${path.slice(0, 200)}`);
    }
  }
  if (
    !Array.isArray(data.tests) ||
    data.tests.some((test) => typeof test !== "string" || !test.trim())
  ) {
    throw new Error("tests must be a list of dotted unittest selectors.");
  }
}

function captureOutput() {
  let output = "";
  let truncated = false;
  const decoders = [];
  function truncate() {
    truncated = true;
    output = output.slice(0, OUTPUT_LIMIT - TRUNCATED.length) + TRUNCATED;
  }
  function append(text) {
    if (truncated) return;
    const remaining = OUTPUT_LIMIT - output.length;
    output += text.slice(0, remaining);
    if (text.length > remaining) {
      truncate();
    }
  }
  return {
    append,
    writer() {
      // Raw writes, rather than line buffering, also bound endless print(end="").
      const decoder = new TextDecoder();
      decoders.push(decoder);
      return {
        write(bytes) {
          if (!truncated) {
            const remaining = OUTPUT_LIMIT - output.length;
            const chunk = bytes.subarray(0, remaining * 4 + 4);
            append(decoder.decode(chunk, { stream: true }));
            if (chunk.length < bytes.length && !truncated) truncate();
          }
          return bytes.length;
        },
      };
    },
    text() {
      for (const decoder of decoders) append(decoder.decode());
      return output;
    },
  };
}

let used = false;
self.onmessage = async ({ data }) => {
  const id = data?.id ?? null;
  const started = performance.now();
  try {
    if (used) throw new Error("Create a fresh Python worker for each Run.");
    used = true;
    validateRequest(data);
    const output = captureOutput();
    const runtimeURL = new URL(data.runtimeURL, self.location.href);
    const { loadPyodide } = await import(runtimeURL.href);
    const pyodide = await loadPyodide({
      indexURL: new URL(".", runtimeURL).href,
      stdin: () => null,
      stdout: (text) => output.append(text + "\n"),
      stderr: (text) => output.append(text + "\n"),
    });
    pyodide.setStdout(output.writer());
    pyodide.setStderr(output.writer());
    pyodide.FS.mkdirTree("/workspace");
    for (const [path, source] of Object.entries(data.files)) {
      const destination = `/workspace/${path}`;
      pyodide.FS.mkdirTree(destination.slice(0, destination.lastIndexOf("/")));
      pyodide.FS.writeFile(destination, source, { encoding: "utf8" });
    }
    pyodide.FS.chdir("/workspace");
    // A separate globals dict keeps learner modules out of the runner namespace.
    const globals = pyodide.runPython("dict()");
    let tests;
    try {
      globals.set("_worker_selectors", JSON.stringify(data.tests));
      globals.set("_worker_detail_limit", DETAIL_LIMIT);
      tests = JSON.parse(await pyodide.runPythonAsync(RUN_TESTS, { globals })).map(
        (test) => ({
          ...test,
          // Python counts Unicode code points; bound JS UTF-16 lengths too.
          id: boundedDetail(test.id),
          detail: boundedDetail(test.detail),
        }),
      );
    } finally {
      globals.destroy();
    }
    self.postMessage({
      id,
      kind: "result",
      tests,
      output: output.text(),
      duration: performance.now() - started,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    self.postMessage({ id, kind: "error", message: boundedDetail(message) });
  }
};
