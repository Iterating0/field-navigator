import { test } from "node:test";
import assert from "node:assert/strict";
import { createInstance } from "i18next";
import { zh as appZh, en as appEn } from "../src/locales/app.ts";
import {
  zh as workspaceZh,
  en as workspaceEn,
} from "../src/locales/workspace.ts";
import { zh as resultsZh, en as resultsEn } from "../src/locales/results.ts";
import {
  detectLanguage,
  readLanguage,
  saveLanguage,
  LANGUAGE_STORAGE_KEY,
} from "../src/i18n/language.ts";

test("explicit language wins, and existing workspaces keep their original UI", () => {
  assert.equal(detectLanguage("en", ["zh-CN"], true), "en");
  assert.equal(detectLanguage("zh-CN", ["en-US"]), "zh-CN");
  assert.equal(detectLanguage(null, ["en-US"], true), "zh-CN");
  assert.equal(detectLanguage(null, ["de-DE", "en-GB"]), "en");
  assert.equal(detectLanguage("unsupported", ["zh-Hans"]), "zh-CN");
  assert.equal(detectLanguage(null, ["fr-FR"]), "zh-CN");
});

test("language preference round-trips independently of research and notes", () => {
  const entries = new Map([["private-note", "Original text"]]);
  const storage = {
    getItem(key: string) {
      return entries.get(key) ?? null;
    },
    setItem(key: string, value: string) {
      entries.set(key, value);
    },
  };
  assert.equal(saveLanguage(storage, "en"), true);
  assert.equal(entries.get(LANGUAGE_STORAGE_KEY), "en");
  assert.equal(readLanguage(storage, ["zh-CN"]), "en");
  assert.equal(entries.get("private-note"), "Original text");
});

test("blocked browser storage does not prevent a usable language", () => {
  const blocked = {
    getItem() {
      throw new Error("Storage disabled");
    },
    setItem() {
      throw new Error("Storage disabled");
    },
  };
  assert.equal(readLanguage(blocked, ["en-US"]), "en");
  assert.equal(saveLanguage(blocked, "en"), false);
});

function flatten(value: object, prefix = ""): Record<string, string> {
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, child]) => {
      const path = prefix ? `${prefix}.${key}` : key;
      return typeof child === "string"
        ? [[path, child]]
        : Object.entries(flatten(child, path));
    }),
  );
}

test("every UI message and interpolation variable exists in both languages", () => {
  for (const [namespace, zh, en] of [
    ["app", appZh, appEn],
    ["workspace", workspaceZh, workspaceEn],
    ["results", resultsZh, resultsEn],
  ] as const) {
    const chinese = flatten(zh),
      english = flatten(en);
    assert.deepEqual(
      Object.keys(english).sort(),
      Object.keys(chinese).sort(),
      namespace,
    );
    for (const key of Object.keys(chinese)) {
      const variables = (text: string) =>
        [...text.matchAll(/\{\{\s*([^},]+)(?:,[^}]+)?\}\}/g)]
          .map((match) => match[1].trim())
          .sort();
      assert.ok(
        english[key].trim(),
        `${namespace}.${key} has an English translation`,
      );
      assert.deepEqual(
        variables(english[key]),
        variables(chinese[key]),
        `${namespace}.${key}`,
      );
    }
  }
});

test("actual i18next lookup handles English plurals and switching without reloading", async () => {
  const instance = createInstance();
  await instance.init({
    lng: "en",
    fallbackLng: "zh-CN",
    initAsync: false,
    resources: {
      en: { workspace: workspaceEn, results: resultsEn },
      "zh-CN": { workspace: workspaceZh, results: resultsZh },
    },
  });
  assert.match(
    instance.t("graph.paperCount", { ns: "results", count: 1 }),
    /^1 paper$/,
  );
  assert.match(
    instance.t("graph.paperCount", { ns: "results", count: 2 }),
    /^2 papers$/,
  );
  await instance.changeLanguage("zh-CN");
  assert.equal(
    instance.t("start.title", { ns: "workspace" }),
    "从研究问题开始。",
  );
  await instance.changeLanguage("en");
  assert.notEqual(
    instance.t("start.title", { ns: "workspace" }),
    "从研究问题开始。",
  );
});
