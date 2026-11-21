"""Qualification driver for isolated CI. See the reports for execution status."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

PIN = "9ab3c8cd13c9c2617a45689f12b7fcd4c7473ec7"
CANDIDATE = "a431a96c4f6ed556926b98119079631117ebb9f7"
BUNDLE = Path(__file__).resolve().parents[1]
PATCH_HASHES = {
    "integration-regressions.patch": "899ea4b225b10b8923582e64af881c1736f389acc44afbb3cd6dc2bf4fa6348c",
    "selected-source.patch": "6ff324b660728eee93b9f2e03f608cb5dccf92f90bbb3dc518e5d435fee1b372",
}
BASELINE_HASHES = {
    "modules/imgproc/src/linefit.cpp": "e7d88be5052d68a41c4f51f71c07eaef7370ae2d87707133196a1edc9f25f950",
    "modules/imgproc/test/test_convhull.cpp": "6245047716a68902a349d21af9cbda00bf32fbfbd2ae4719f4f80e5a839d45ba",
    "modules/core/src/lapack.dispatch.cpp": "f9134b11e01527ac402e47d94092d3f9693fb60e18917466179c17afb92ae4b8",
}
CANDIDATE_HASHES = {
    "modules/imgproc/src/linefit.cpp": "18c8f4a1df750cad3d55613bcba53d179241290676775206dcc3f658961d29aa",
    "modules/imgproc/test/test_convhull.cpp": "59f9571db1e0b69c3cfea412965bd4e196723847e144a2fe2fa6eb51ab4850a3",
}
EXPECTED_RED = {f"Imgproc_FitLine.{name}" for name in (
    "l2_3d_translated_exact_line", "l2_3d_constant_large_coordinates",
    "l2_3d_tiny_exact_line", "l2_3d_separated_constant_blocks")}
TINY_STOCK_TEST = "Imgproc_FitLine.l2_3d_tiny_exact_line"
DIAGNOSTIC = "Mission19_Diagnostics.LoadedModules"
CONTROLS = {f"Mission19_Controls.{name}" for name in (
    "ExtremeScales", "BlockBoundariesAndReversal", "TiedObjective")}
NATIVE_CASES = EXPECTED_RED | {"Imgproc_FitLine.regression_15083", "Imgproc_FitLine.regression_4903"} | {
    f"fitLine_Modes.accuracy/{i}" for i in range(24)}
FILTER = "*FitLine*:*fitLine*:" + DIAGNOSTIC
OPTIONS = (
    "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    "-DBUILD_LIST=imgproc,ts", "-DBUILD_TESTS=ON", "-DBUILD_PERF_TESTS=OFF",
    "-DBUILD_EXAMPLES=OFF", "-DBUILD_SHARED_LIBS=ON", "-DBUILD_opencv_world=OFF",
    "-DBUILD_JAVA=OFF", "-DBUILD_opencv_python3=OFF", "-DENABLE_LTO=OFF",
    "-DWITH_IPP=OFF", "-DWITH_OPENCL=OFF", "-DWITH_ITT=OFF", "-DWITH_FFMPEG=OFF",
    "-DWITH_GSTREAMER=OFF", "-DWITH_GTK=OFF", "-DWITH_QT=OFF", "-DWITH_OPENGL=OFF",
    "-DWITH_JPEG=OFF", "-DWITH_PNG=OFF", "-DWITH_TIFF=OFF", "-DWITH_WEBP=OFF",
    "-DWITH_JASPER=OFF", "-DWITH_OPENJPEG=OFF", "-DWITH_OPENEXR=OFF",
    "-DWITH_AVIF=OFF", "-DWITH_GIF=OFF", "-DWITH_LAPACK=OFF")


def run(command, log, expected=0, **kwargs):
    command = [str(value) for value in command]
    print("+", json.dumps(command), flush=True)
    with log.open("wb") as stream:
        stream.write((json.dumps(command) + "\n").encode())
        stream.flush()
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, **kwargs)
    if result.returncode != expected:
        tail = log.read_text(errors="replace").splitlines()[-25:]
        raise RuntimeError(f"{log}: exit {result.returncode}, expected {expected}\n" + "\n".join(tail))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_digest(path, expected):
    actual = digest(path)
    if actual != expected:
        raise RuntimeError(f"SHA-256 mismatch for {path}: expected {expected}, actual {actual}")
    return actual


def verify_sources(source, expected):
    return {name: require_digest(source/name, value) for name, value in expected.items()}


def test_results(xml):
    records = {}
    for suite in ET.parse(xml).getroot().iter("testsuite"):
        for test in suite.findall("testcase"):
            name = suite.attrib["name"] + "." + test.attrib["name"]
            if (name in records or test.find("skipped") is not None
                    or test.find("error") is not None or test.get("status") != "run"):
                raise RuntimeError(f"Unexpected XML case: {name}")
            records[name] = test.find("failure") is not None
    return records


def verify_xml(xml, failures, count, exact_names=None, optional_failure=None):
    cases = test_results(xml)
    actual = {name for name, failed in cases.items() if failed}
    required = failures - {optional_failure}
    if (len(cases) != count or not required <= actual <= failures
            or (exact_names and set(cases) != exact_names)
            or (optional_failure and optional_failure not in cases)):
        raise RuntimeError(f"{xml}: {len(cases)} ran, failures {sorted(actual)}")
    return set(cases)


def find_one(paths, description):
    candidates = list(paths)
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one {description}: {candidates}")
    return candidates[0]


def verify_modules(log, build):
    lines = log.read_text(errors="replace").splitlines()
    paths = [Path(line.removeprefix("M19_MODULE ")).resolve()
             for line in lines if line.startswith("M19_MODULE ")]
    for module in ("opencv_core", "opencv_imgproc"):
        path = find_one((p for p in paths if module in p.name.lower()), module)
        if not path.is_relative_to(build.resolve()) or not path.is_file():
            raise RuntimeError(f"Unexpected runtime library: {path}")
    return [p for p in paths if "opencv_" in p.name.lower()]


def enable_msvc(output):
    vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    vs = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires",
        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
        text=True).strip()
    if not vs:
        raise RuntimeError("No usable MSVC x64 installation")
    devcmd = Path(vs) / "Common7/Tools/VsDevCmd.bat"
    # cmd /s strips the outer quote pair. Keep the inner quotes around the batch path.
    command = f'cmd.exe /d /s /c ""{devcmd}" -no_logo -arch=amd64 -host_arch=amd64 && set"'
    result = subprocess.check_output(command, text=True, errors="replace")
    for line in result.splitlines():
        key, sep, value = line.partition("=")
        if sep and key:
            os.environ[key] = value
    # Avoid writing the full CI environment, which can contain credentials.
    versions = {key: os.environ.get(key) for key in
                ("VCToolsVersion", "WindowsSDKVersion", "VSCMD_ARG_TGT_ARCH", "VSCMD_ARG_HOST_ARCH")}
    (output/"msvc-environment.json").write_text(json.dumps(versions, indent=2))
    probe = output/"msvc-x64.cpp"
    probe.write_text("#ifndef _M_X64\n#error Expected MSVC x64 target\n#endif\nint mission19_probe;\n")
    run(["cl", "/nologo", "/Bv", "/c", probe, f"/Fo{output/'msvc-x64.obj'}"], output/"compiler.log")
    run(["where.exe", "cl", "link", "dumpbin"], output/"compiler-paths.log")


def instrument_eigen(source):
    path = source/"modules/core/src/lapack.dispatch.cpp"
    text = path.read_text()
    for suffix, matrix in (("F64", "MatrixXd"), ("F32", "MatrixXf")):
        solver = text.index(f"Eigen::SelfAdjointEigenSolver<Eigen::{matrix}> es;")
        token = "if ( es.info() == Eigen::Success )\n        {"
        pos = text.index(token, solver) + len(token)
        text = text[:pos] + f'\n            std::fprintf(stderr, "M19_EIGEN_{suffix}\\n");' + text[pos:]
    header = '#include "precomp.hpp"'
    if text.count(header) != 1:
        raise RuntimeError("Unexpected core include placement")
    path.write_text(text.replace(header, header + "\n#include <cstdio>"))


def evidence(artifacts, phase, source, build, exe, loaded, eigen):
    line = source/"modules/imgproc/src/linefit.cpp"
    test = source/"modules/imgproc/test/test_convhull.cpp"
    lines = [f"{digest(file)}  {file}" for file in (line, test, exe, *loaded)]
    (artifacts/f"{phase}-sha256.txt").write_text("\n".join(lines)+"\n")
    commands = json.loads((build/"compile_commands.json").read_text())
    selected = [entry for entry in commands if Path(entry["file"]).name in
                {"lapack.dispatch.cpp", "linefit.cpp", "test_convhull.cpp"}]
    if {Path(entry["file"]).name for entry in selected} != {"lapack.dispatch.cpp","linefit.cpp","test_convhull.cpp"}:
        raise RuntimeError("Missing exact core, imgproc or test compiler command")
    if eigen and not any(Path(row["file"]).name == "lapack.dispatch.cpp" and "eigen3" in row["command"].lower()
                         for row in selected):
        raise RuntimeError("Core compiler command omits Eigen include location")
    (artifacts/f"{phase}-compile-commands.json").write_text(json.dumps(selected, indent=2))


def windows_artifacts(artifacts, phase, build, exe, loaded):
    obj = find_one(build.rglob("linefit.cpp.obj"), "linefit object")
    shutil.copyfile(obj, artifacts/f"{phase}-linefit.cpp.obj")
    run(["dumpbin", "/SYMBOLS", obj], artifacts/f"{phase}-symbols.log")
    run(["dumpbin", "/DISASM", "/RELOCATIONS", obj], artifacts/f"{phase}-object-assembly.log")
    run(["dumpbin", "/HEADERS", exe], artifacts/f"{phase}-exe-headers.log")
    for file in [exe, *loaded]:
        run(["dumpbin", "/DEPENDENTS", file], artifacts/f"{phase}-{file.name}-dependencies.log")
    imgproc = find_one((p for p in loaded if "opencv_imgproc" in p.name.lower()), "imgproc DLL")
    run(["dumpbin", "/PDATA", imgproc], artifacts/f"{phase}-imgproc-pdata.log")
    if phase == "green" and "fitLine3D_L2" not in (artifacts/"green-symbols.log").read_text(errors="replace"):
        raise RuntimeError("L2 helper symbol missing; inspect MSVC code-generation evidence")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("msvc","eigen","local-config"))
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--upstream", default="https://github.com/opencv/opencv.git")
    args = parser.parse_args()
    scratch, out = args.scratch.resolve(), args.artifacts.resolve()
    scratch.mkdir(parents=True, exist_ok=False)
    out.mkdir(parents=True, exist_ok=True)
    source, build = scratch/"source", scratch/"build"
    source.mkdir()
    used = shutil.disk_usage(scratch)
    metadata = {key: os.environ.get(key) for key in ("ImageOS","ImageVersion","RUNNER_OS","RUNNER_ARCH","GITHUB_SHA","GITHUB_REF","GITHUB_EVENT_NAME")}
    metadata.update(opencv_pin=PIN, contribution=CANDIDATE, free_bytes=used.free, python=sys.version)
    if args.backend == "msvc":
        run(["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_ComputerSystem | Select-Object NumberOfLogicalProcessors,TotalPhysicalMemory; Get-PSDrive -PSProvider FileSystem"],
            out/"windows-resources.log")
    (out/"runner.json").write_text(json.dumps(metadata, indent=2))
    if args.backend == "msvc":
        if sys.platform != "win32":
            raise RuntimeError("Native Windows Python required")
        enable_msvc(out)
    else:
        run(["c++","--version"], out/"compiler.log")
    for tool in ("cmake","ninja"):
        run([tool,"--version"], out/f"{tool}-version.log")
    run(["git","init","--quiet"], out/"git-init.log", cwd=source)
    run(["git","config","core.autocrlf","false"], out/"git-line-endings.log", cwd=source)
    run(["git","fetch","--depth","1",args.upstream,PIN], out/"git-fetch.log", cwd=source)
    run(["git","checkout","--detach",PIN], out/"git-checkout.log", cwd=source)
    actual_pin = subprocess.check_output(["git","rev-parse","HEAD"], cwd=source, text=True).strip()
    if actual_pin != PIN:
        raise RuntimeError(f"Wrong OpenCV checkout: {actual_pin}")
    baseline = verify_sources(source, BASELINE_HASHES)
    (out/"baseline-source-sha256.json").write_text(json.dumps(baseline, indent=2))
    reports = {}
    for name, expected_hash in PATCH_HASHES.items():
        patch = out/name
        # Canonical LF patch bytes are the archived input even after a Windows checkout.
        patch.write_bytes((BUNDLE/"patches"/name).read_bytes().replace(b"\r\n", b"\n"))
        reports[name] = require_digest(patch, expected_hash)
        run(["git","apply","--check",patch], out/f"{name}.check.log", cwd=source)
    (out/"input-patches.json").write_text(json.dumps(reports, indent=2))
    run(["git","apply",out/"integration-regressions.patch"], out/"regression-apply.log", cwd=source)
    test = source/"modules/imgproc/test/test_convhull.cpp"
    require_digest(test, CANDIDATE_HASHES["modules/imgproc/test/test_convhull.cpp"])
    with test.open("ab") as stream:
        stream.write(b"\n" + (BUNDLE/"ci/qualification-tests.inc").read_bytes().replace(b"\r\n", b"\n"))
    if args.backend == "eigen":
        run(["dpkg-query","-W","libeigen3-dev"], out/"eigen-package.log")
        shutil.copyfile("/usr/include/eigen3/Eigen/src/Core/util/Macros.h", out/"eigen-Macros.h")
        instrument_eigen(source)
        run(["git","diff","--","modules/core/src/lapack.dispatch.cpp"],
            out/"eigen-instrumentation.diff.log", cwd=source)
    flags = [*OPTIONS, "-DWITH_EIGEN=ON" if args.backend=="eigen" else "-DWITH_EIGEN=OFF"]
    if args.backend == "eigen":
        flags += ["-DEigen3_DIR=/usr/share/eigen3/cmake", "-DCMAKE_CXX_FLAGS=-ffp-contract=off"]
    if args.backend == "msvc":
        flags += ["-DCMAKE_CXX_COMPILER=cl", "-DCMAKE_CXX_FLAGS=/fp:precise"]
    run(["cmake","-S",source,"-B",build,*flags], out/"configure.log")
    shutil.copyfile(build/"CMakeCache.txt", out/"CMakeCache.txt")
    config = build/"cvconfig.h"
    shutil.copyfile(config, out/"cvconfig.h")
    has_eigen = re.search(r"^#define HAVE_EIGEN(?:\s|$)", config.read_text(), re.MULTILINE) is not None
    if has_eigen != (args.backend == "eigen"):
        raise RuntimeError("Configured Eigen backend differs from requested backend")
    run(["ninja","-C",build,"-t","targets","all"], out/"ninja-targets.log")
    targets = (out/"ninja-targets.log").read_text(errors="replace")
    if not re.search(r"^(?:bin/)?opencv_test_imgproc(?:\.exe)?:\s", targets, re.MULTILINE):
        raise RuntimeError("Configured Ninja graph omits opencv_test_imgproc")
    if args.backend == "local-config":
        return

    initial = digest(test)
    tested_names = NATIVE_CASES | {DIAGNOSTIC}
    stock_core_hash = None
    stock_imgproc_hash = None
    for phase in ("red", "green"):
        if phase == "green":
            run(["git","apply",out/"selected-source.patch"], out/"candidate-apply.log", cwd=source)
        require_digest(source/"modules/imgproc/src/linefit.cpp",
                       (BASELINE_HASHES if phase == "red" else CANDIDATE_HASHES)["modules/imgproc/src/linefit.cpp"])
        if digest(test) != initial:
            raise RuntimeError("RED/GREEN test source mismatch")
        run(["git","diff","--check"], out/f"{phase}-diff-check.log", cwd=source)
        run(["cmake","--build",build,"--target","opencv_test_imgproc","--parallel","2","--verbose"],
            out/f"{phase}-build.log")
        exe = find_one(build.rglob("opencv_test_imgproc.exe" if sys.platform=="win32" else "opencv_test_imgproc"),
                       "imgproc test executable")
        env = os.environ.copy()
        if sys.platform == "win32":
            expected = [find_one(build.rglob(f"{module}*.dll"), module) for module in
                        ("opencv_core", "opencv_imgproc")]
            paths = sorted({str(file.parent) for file in [exe, *expected]})
            env["PATH"] = os.pathsep.join([*paths, env["PATH"]])
        env["OPENCV_FOR_THREADS_NUM"] = "1"
        xml, log = out/f"{phase}.xml", out/f"{phase}-tests.log"
        run([exe, f"--gtest_filter={FILTER}", f"--gtest_output=xml:{xml}"], log,
            expected=1 if phase=="red" else 0, env=env, cwd=build)
        # The tiny stock case specifically stresses Jacobi's absolute threshold.
        # Eigen may resolve its subnormal matrix, so record either result on RED.
        optional = TINY_STOCK_TEST if phase == "red" and args.backend == "eigen" else None
        tested_names = verify_xml(xml, EXPECTED_RED if phase=="red" else set(), 31, tested_names, optional)
        (out/f"{phase}-case-results.json").write_text(json.dumps(test_results(xml), indent=2))
        if DIAGNOSTIC not in tested_names:
            raise RuntimeError("Missing in-process module evidence")
        loaded = verify_modules(log, build)
        evidence(out, phase, source, build, exe, loaded, args.backend == "eigen")
        imgproc = find_one((p for p in loaded if "opencv_imgproc" in p.name.lower()), "loaded imgproc")
        core = find_one((p for p in loaded if "opencv_core" in p.name.lower()), "loaded core")
        if phase == "red":
            stock_imgproc_hash = digest(imgproc)
            stock_core_hash = digest(core)
        else:
            if digest(imgproc) == stock_imgproc_hash:
                raise RuntimeError("GREEN loaded the same imgproc binary as RED")
            require_digest(core, stock_core_hash)
        if args.backend == "msvc":
            windows_artifacts(out, phase, build, exe, loaded)
        if args.backend == "eigen":
            marker = "M19_EIGEN_F32" if phase=="red" else "M19_EIGEN_F64"
            targeted = out/f"{phase}-dispatch-tests.log"
            # Prove the intended branch on an analytic L2 regression, not on a robust invocation.
            run([exe,"--gtest_filter=Imgproc_FitLine.l2_3d_translated_exact_line"], targeted,
                expected=1 if phase=="red" else 0, env=env, cwd=build)
            if marker not in targeted.read_text(errors="replace").splitlines():
                raise RuntimeError(f"{phase}: expected executed solver marker {marker}")
        if phase == "green":
            control_xml = out/"controls.xml"
            run([exe,"--gtest_filter=Mission19_Controls.*", f"--gtest_output=xml:{control_xml}"],
                out/"controls.log", env=env, cwd=build)
            verify_xml(control_xml, set(), len(CONTROLS), CONTROLS)
    metrics = {"free_bytes_after": shutil.disk_usage(scratch).free,
               "build_file_bytes": sum(f.stat().st_size for f in build.rglob("*") if f.is_file())}
    (out/"build-size.json").write_text(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
