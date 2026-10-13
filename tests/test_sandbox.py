"""End-to-end tests: start the real service with uvicorn and run code in real Docker containers.

Build the runner image first: docker build -t algosproj-runner runner
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SECRET = "test-secret"
REPO_ROOT = Path(__file__).resolve().parent.parent
DOUBLE_TESTS = [
    {"input": "21\n", "expected_output": "42"},
    {"input": "-5\n", "expected_output": "-10"},
]


@pytest.fixture(scope="session")
def base_url():
    image = subprocess.run(["docker", "image", "inspect", "algosproj-runner"], capture_output=True)
    if image.returncode != 0:
        pytest.fail("Image algosproj-runner not found. Run: docker build -t algosproj-runner runner")

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=REPO_ROOT,
        env={**os.environ, "SANDBOX_SECRET": SECRET},
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while True:
        try:
            urllib.request.urlopen(f"{url}/health", timeout=1)
            break
        except OSError:
            if time.monotonic() > deadline:
                server.kill()
                pytest.fail("uvicorn did not start")
            time.sleep(0.2)
    yield url
    server.terminate()
    server.wait()


def post_run(base_url, body, secret=SECRET):
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Sandbox-Secret"] = secret
    request = urllib.request.Request(f"{base_url}/run", data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def run(base_url, language, code, test_cases=DOUBLE_TESTS):
    status, body = post_run(base_url, {"language": language, "code": code, "test_cases": test_cases})
    assert status == 200, body
    return body


# --- Every language -----------------------------------------------------------------

CORRECT = {
    "python": "n = int(input())\nprint(n * 2)\n",
    "java": """
import java.util.Scanner;
public class Main {
    public static void main(String[] args) {
        long n = new Scanner(System.in).nextLong();
        System.out.println(n * 2);
    }
}
""",
    "javascript": "const n = parseInt(require('fs').readFileSync(0, 'utf8'));\nconsole.log(n * 2);\n",
    "cpp": """
#include <iostream>
int main() { long long n; std::cin >> n; std::cout << n * 2 << std::endl; }
""",
}

WRONG = {
    "python": "n = int(input())\nprint(n * 3)\n",
    "java": """
import java.util.Scanner;
public class Main {
    public static void main(String[] args) {
        long n = new Scanner(System.in).nextLong();
        System.out.println(n * 3);
    }
}
""",
    "javascript": "const n = parseInt(require('fs').readFileSync(0, 'utf8'));\nconsole.log(n * 3);\n",
    "cpp": """
#include <iostream>
int main() { long long n; std::cin >> n; std::cout << n * 3 << std::endl; }
""",
}

BROKEN = {
    "python": "print(int(input()) * 2\n",
    "java": "public class Main { public static void main(String[] args) { System.out.println(1) } }",
    "javascript": "console.log(;\n",
    "cpp": "int main() { return 0 }",
}

INFINITE_LOOP = {
    "python": "while True:\n    pass\n",
    "java": "public class Main { public static void main(String[] args) { while (true) {} } }",
    "javascript": "while (true) {}\n",
    "cpp": "int main() { volatile int x = 0; while (true) { x++; } }",
}

ALL_LANGUAGES = ["python", "java", "javascript", "cpp"]


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_correct_solution_passes(base_url, language):
    body = run(base_url, language, CORRECT[language])
    assert body["status"] == "passed", body
    assert [r["actual"] for r in body["results"]] == ["42", "-10"]
    assert all(r["passed"] and r["error"] is None for r in body["results"])
    assert body["compile_error"] is None


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_wrong_answer_fails(base_url, language):
    body = run(base_url, language, WRONG[language])
    assert body["status"] == "failed", body
    first = body["results"][0]
    assert first["passed"] is False
    assert first["actual"] == "63"
    assert first["expected"] == "42"


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_compile_or_syntax_error(base_url, language):
    body = run(base_url, language, BROKEN[language])
    assert body["status"] == "error", body
    message = body["compile_error"] or body["results"][0]["error"]
    assert message


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_infinite_loop_is_stopped(base_url, language):
    started = time.monotonic()
    body = run(base_url, language, INFINITE_LOOP[language], [{"input": "", "expected_output": "x"}])
    assert time.monotonic() - started < 45
    assert body["status"] in ("timeout", "failed"), body
    assert body["results"][0]["passed"] is False


# --- Adversarial: python, java, cpp ---------------------------------------------------

MEMORY_HOG = {
    "python": "chunks = []\nwhile True:\n    chunks.append(b'x' * (10 * 1024 * 1024))\n",
    "java": """
import java.util.*;
public class Main {
    public static void main(String[] args) {
        List<byte[]> chunks = new ArrayList<>();
        while (true) {
            byte[] b = new byte[10 << 20];
            Arrays.fill(b, (byte) 1);
            chunks.add(b);
        }
    }
}
""",
    "cpp": """
#include <vector>
int main() {
    std::vector<std::vector<char>> chunks;
    while (true) chunks.emplace_back(10 << 20, 'x');
}
""",
}

NETWORK = {
    "python": """
import socket
try:
    socket.create_connection(("1.1.1.1", 80), timeout=2)
    print("connected")
except OSError:
    print("blocked")
""",
    "java": """
import java.net.*;
public class Main {
    public static void main(String[] args) {
        try (Socket s = new Socket()) {
            s.connect(new InetSocketAddress("1.1.1.1", 80), 2000);
            System.out.println("connected");
        } catch (Exception e) {
            System.out.println("blocked");
        }
    }
}
""",
    "cpp": """
#include <arpa/inet.h>
#include <cstdio>
#include <sys/socket.h>
int main() {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(80);
    inet_pton(AF_INET, "1.1.1.1", &addr.sin_addr);
    if (fd >= 0 && connect(fd, (sockaddr*)&addr, sizeof addr) == 0) puts("connected");
    else puts("blocked");
}
""",
}

FILE_WRITE = {
    "python": """
try:
    with open("/evil.txt", "w") as f:
        f.write("x")
    root = "written"
except OSError:
    root = "blocked"
with open("/tmp/ok.txt", "w") as f:
    f.write("ok")
print(root, open("/tmp/ok.txt").read())
""",
    "java": """
import java.nio.file.*;
public class Main {
    public static void main(String[] args) throws Exception {
        String root;
        try {
            Files.writeString(Path.of("/evil.txt"), "x");
            root = "written";
        } catch (Exception e) {
            root = "blocked";
        }
        Files.writeString(Path.of("/tmp/ok.txt"), "ok");
        System.out.println(root + " " + Files.readString(Path.of("/tmp/ok.txt")));
    }
}
""",
    "cpp": """
#include <fstream>
#include <iostream>
#include <string>
int main() {
    std::ofstream evil("/evil.txt");
    const char* root = evil ? "written" : "blocked";
    { std::ofstream ok("/tmp/ok.txt"); ok << "ok"; }
    std::ifstream in("/tmp/ok.txt");
    std::string s;
    in >> s;
    std::cout << root << " " << s << std::endl;
}
""",
}

FORK_BOMB = {
    "python": """
import os
while True:
    try:
        os.fork()
    except OSError:
        pass
""",
    # The JVM can't fork itself cheaply; threads count against the pids limit too.
    "java": """
public class Main {
    public static void main(String[] args) {
        while (true) {
            new Thread(() -> {
                try { Thread.sleep(60000); } catch (InterruptedException e) {}
            }).start();
        }
    }
}
""",
    "cpp": "#include <unistd.h>\nint main() { while (true) fork(); }",
}

ADVERSARIAL_LANGUAGES = ["python", "java", "cpp"]
ONE_TEST = [{"input": "", "expected_output": "unused"}]


@pytest.mark.parametrize("language", ADVERSARIAL_LANGUAGES)
def test_memory_hog_is_stopped(base_url, language):
    body = run(base_url, language, MEMORY_HOG[language], ONE_TEST)
    assert body["status"] in ("error", "timeout"), body
    assert body["results"][0]["passed"] is False


@pytest.mark.parametrize("language", ADVERSARIAL_LANGUAGES)
def test_network_is_blocked(base_url, language):
    body = run(base_url, language, NETWORK[language], [{"input": "", "expected_output": "blocked"}])
    assert body["status"] == "passed", body


@pytest.mark.parametrize("language", ADVERSARIAL_LANGUAGES)
def test_root_filesystem_is_read_only_but_tmp_is_writable(base_url, language):
    body = run(base_url, language, FILE_WRITE[language], [{"input": "", "expected_output": "blocked ok"}])
    assert body["status"] == "passed", body


@pytest.mark.parametrize("language", ADVERSARIAL_LANGUAGES)
def test_fork_bomb_is_stopped(base_url, language):
    started = time.monotonic()
    body = run(base_url, language, FORK_BOMB[language], ONE_TEST)
    assert time.monotonic() - started < 45
    assert body["status"] in ("timeout", "error"), body
    assert body["results"][0]["passed"] is False


# --- Expected outputs are hidden from user code ---------------------------------------

MARKER = "SECRET_EXPECTED_12345"

# Each program searches the environment, /proc/1/environ, /proc/self/environ and every
# file under /tmp and the working directory, also base64-decoding anything that looks
# like base64 (the submission travels base64-encoded). It prints "HITS [...]" first, so
# a find survives the output being cut to 500 characters, then everything it found.
# The marker is built at runtime, so the program's own source file doesn't contain it.
SNOOP = {
    "python": r"""
import base64, os, re
needle = "SECRET_EXPECTED_" + str(12345)
found, notes = [], []

def add(where, data):
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    found.append((where, data))
    for token in re.split(r"[\s\x00]+", data):
        for candidate in (token, token.split("=", 1)[-1]):
            if re.fullmatch(r"[A-Za-z0-9+/]{8,}={0,2}", candidate):
                try:
                    decoded = base64.b64decode(candidate + "==").decode("utf-8", "replace")
                    found.append((where + " (base64)", decoded))
                except Exception:
                    pass

for key, value in os.environ.items():
    add("env " + key, value)
for path in ("/proc/1/environ", "/proc/self/environ"):
    try:
        add(path, open(path, "rb").read())
    except OSError as e:
        notes.append(f"{path} blocked {e.errno}")
for root in ("/tmp", os.getcwd()):
    for dirpath, _, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            try:
                add(path, open(path, "rb").read())
            except OSError as e:
                notes.append(f"{path} unreadable {e.errno}")

print("HITS", [where for where, text in found if needle in text])
print("\n".join(notes))
for where, text in found:
    print(where, text[:200])
""",
    "javascript": r"""
const fs = require('fs');
const path = require('path');
const needle = 'SECRET_EXPECTED_' + String(12345);
const found = [];
const notes = [];

function add(where, data) {
  data = String(data);
  found.push([where, data]);
  for (const token of data.split(/[\s\0]+/)) {
    for (const candidate of [token, token.slice(token.indexOf('=') + 1)]) {
      if (/^[A-Za-z0-9+/]{8,}={0,2}$/.test(candidate)) {
        found.push([where + ' (base64)', Buffer.from(candidate, 'base64').toString('utf8')]);
      }
    }
  }
}

function walk(dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (e) {
    notes.push(dir + ' unlistable ' + e.code);
    return;
  }
  for (const entry of entries) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p);
    else if (entry.isFile()) {
      try {
        add(p, fs.readFileSync(p));
      } catch (e) {
        notes.push(p + ' unreadable ' + e.code);
      }
    }
  }
}

for (const [key, value] of Object.entries(process.env)) add('env ' + key, value);
for (const p of ['/proc/1/environ', '/proc/self/environ']) {
  try {
    add(p, fs.readFileSync(p));
  } catch (e) {
    notes.push(p + ' blocked ' + e.code);
  }
}
walk('/tmp');
walk(process.cwd());

console.log('HITS ' + JSON.stringify(found.filter(([, text]) => text.includes(needle)).map(([where]) => where)));
console.log(notes.join('\n'));
for (const [where, text] of found) console.log(where, text.slice(0, 200));
""",
}


@pytest.mark.parametrize("language", ["python", "javascript"])
def test_expected_output_is_hidden_from_user_code(base_url, language):
    body = run(base_url, language, SNOOP[language], [{"input": "1\n", "expected_output": MARKER}])
    assert body["status"] == "failed", body
    result = body["results"][0]
    assert result["error"] is None, result
    assert result["actual"].startswith("HITS []"), result["actual"]
    # "expected" echoes the expected output back by design; no other field may contain it.
    for r in body["results"]:
        del r["expected"]
    assert MARKER not in json.dumps(body)


# --- Request validation ---------------------------------------------------------------

VALID_BODY = {"language": "python", "code": CORRECT["python"], "test_cases": DOUBLE_TESTS}


def test_missing_secret_is_rejected(base_url):
    status, _ = post_run(base_url, VALID_BODY, secret=None)
    assert status == 401


def test_wrong_secret_is_rejected(base_url):
    status, _ = post_run(base_url, VALID_BODY, secret="wrong")
    assert status == 401


def test_unknown_language_is_rejected(base_url):
    status, _ = post_run(base_url, {**VALID_BODY, "language": "ruby"})
    assert status == 400


# Keep this last: pytest runs tests in file order.
def test_no_containers_left_behind(base_url):
    # Run containers are named algosproj-run-*; the filter skips other algosproj
    # containers on this machine, such as algosproj-mysql.
    names = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=algosproj-run-", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert names == []
