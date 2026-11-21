# OpenCV 4.x line-fit qualification

This branch drives two disposable CI builds of OpenCV at
`9ab3c8cd13c9c2617a45689f12b7fcd4c7473ec7` to qualify the exact
two-file contribution `a431a96c4f6ed556926b98119079631117ebb9f7`.

A push to `mission19-fitline4-qualification` triggers both jobs. Each applies
the unchanged analytic tests to the pinned source, verifies the expected stock
test failures, then applies the production patch and rebuilds the imgproc test
target. Candidate qualification requires all 30 native cases and three
additional controls, evidence of the OpenCV libraries actually loaded, and
matching test sources before and after the implementation change. Both builds
use two compiler jobs. The Ubuntu job installs Eigen inside its disposable
runner and instruments the real OpenCV eigensolver success branches. The Windows
job compiles a native x64 probe and archives object and DLL stack evidence.

Review the downloaded logs, XML, loaded-binary hashes, command lines and Windows
object disassembly before recording qualification. Compare stack allocation
and page probes on the public and robust paths against the isolated L2 path.
Only the stock tiny-scale test is allowed to pass when using the Eigen
backend. Both builds require it to pass with the correction.

The archived patches represent only the contribution. The build driver appends
temporary diagnostics and controls to both CI test builds.
