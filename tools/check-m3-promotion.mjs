#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

import {
  PromotionErrorCode,
  PromotionReadinessError,
  validateM3Promotion,
} from "../validation/m3-promotion/readiness.mjs";

function parseArguments(values) {
  const result = {
    repositoryRoot: process.cwd(),
    manifestPath: "validation/manifests/m3-entry-gates.json",
    readinessPath: "validation/manifests/m3-promotion-readiness.json",
    revision: null,
  };
  const names = new Map([
    ["--repository-root", "repositoryRoot"],
    ["--manifest", "manifestPath"],
    ["--readiness", "readinessPath"],
    ["--revision", "revision"],
  ]);
  for (let index = 0; index < values.length; index += 2) {
    const key = names.get(values[index]);
    const value = values[index + 1];
    if (!key || typeof value !== "string" || value.length === 0) {
      throw new PromotionReadinessError(PromotionErrorCode.INPUT_INVALID);
    }
    result[key] = value;
  }
  return result;
}

function git(repositoryRoot, arguments_) {
  return execFileSync("git", arguments_, {
    cwd: repositoryRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
    windowsHide: true,
  }).trim();
}

function emit(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

try {
  const arguments_ = parseArguments(process.argv.slice(2));
  const repositoryRoot = resolve(arguments_.repositoryRoot);
  const head = git(repositoryRoot, ["rev-parse", "--verify", "HEAD"]);
  if (arguments_.revision !== null && arguments_.revision !== head) {
    throw new PromotionReadinessError(PromotionErrorCode.REVISION_MISMATCH);
  }
  if (git(repositoryRoot, ["status", "--porcelain=v1", "--untracked-files=all"]) !== "") {
    throw new PromotionReadinessError(PromotionErrorCode.WORKTREE_DIRTY);
  }
  const result = validateM3Promotion({
    repositoryRoot,
    manifestPath: arguments_.manifestPath,
    readinessPath: arguments_.readinessPath,
    expectedRevision: head,
  });
  emit(result);
} catch (error) {
  const code =
    error instanceof PromotionReadinessError
      ? error.code
      : PromotionErrorCode.INPUT_INVALID;
  emit({ status: "blocked", code });
  process.exitCode = 1;
}
