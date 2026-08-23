# Licensing and distribution boundary

[한국어](../ko/licensing.md)

## OpenTCAD-owned work

The root MIT License covers original OpenTCAD application code and documentation authored for this repository. The initial GitHub Pages application is entirely within that boundary and contains no copied upstream application or solver code.

## What the MIT License does not cover

The OpenTCAD MIT License does not change the terms of:

- SUPREM-IV.GS source, data, manuals, examples, or derived binaries;
- Gmsh and its GPL obligations;
- DEVSIM and its Apache-2.0 notices;
- base images, package dependencies, or any future imported upstream application code.

The reviewed SUPREM-IV.GS upstream notice is not an MIT license and contains restrictions around commercial transactions. Consequently, OpenTCAD must not publish a SUPREM source archive, prebuilt image, or bundled installer until maintainers have documented a distribution decision and obtained any review or permission that decision requires.

## Foundation-release decision

This foundation release ships no third-party solver source or binary. The static UI uses deterministic reference-preview data created for OpenTCAD and does not claim to reproduce solver output. This lets the MIT application foundation and documentation be published without implying that third-party simulators have been relicensed.

## Gate before solver distribution

Before publishing any solver image or installer, add and review:

1. a component-level copyright and license inventory;
2. exact source provenance and patch-set hashes;
3. a source-offer or build-from-source path where required;
4. image-by-image inclusion and redistribution decisions;
5. NOTICE and attribution material;
6. an SBOM and release-manifest check that rejects an unapproved image.

This document records an engineering boundary, not legal advice.
