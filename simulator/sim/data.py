"""Case data: the releases in the common case schema, the case lists, the anchors, and the record sheet.

The record sheet (presentation P1) is how the patient side sees a case. It is rendered the same way for all four
datasets.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

DATASETS = ("medqa_cs", "agentclinic", "medcasereasoning", "ddxplus")
ARMS = ("control", "single_exposure", "persistence")

# Release category -> heading on the sheet, in sheet order.
CATEGORIES = {
    "symptom": "Symptoms and what happened",
    "medical_history": "Past health",
    "medication": "Medicines",
    "family_history": "Family",
    "habit_exposure": "Habits and exposures",
    "social_background": "Life and background",
}
TIME_TAGS = {"current": "now", "historical": "past", "recurrent": "recurrent", "resolved": "resolved"}


@dataclass
class Case:
    case_id: str
    dataset: str          # release folder name (medqa_cs, agentclinic, medcasereasoning, ddxplus)
    release: str          # release version
    world: str            # "open" or "closed"
    demographics: dict
    opening: list         # fact ids of the opening complaint, in order
    facts: list           # fact objects as in the release
    answered_by: dict     # DDXPlus: catalogue key -> fact ids that answer it
    catalogue: list       # DDXPlus catalogue items (empty in an open world)
    open_items: tuple     # DDXPlus catalogue keys that are open world
    anchor: dict | None   # the worry, from anchors/<dataset>.json, or None

    def resolve_catalogue(self) -> dict:
        """DDXPlus: every catalogue key -> (status, detail). Statuses: fact (listed in the case), answered_by,
        default (unlisted child of a present parent: its absent_text), na (child of a parent that is not present, or
        an item whose `applies_to` names the other sex),
        open (open-world item not in the case), no (a recorded "no": its absent_text)."""
        if not self.catalogue:
            return {}
        listed = {f["key"]: f for f in self.facts}
        status = {}
        for item in self.catalogue:
            key, parent = item["key"], item.get("parent")
            if key in listed:
                status[key] = ("fact", listed[key]["id"])
            elif key in self.answered_by:
                # an empty list marks the item unknown: not recorded, never its default
                ids = self.answered_by[key]
                status[key] = ("answered_by", ids) if ids else ("open", None)
            elif item.get("applies_to") and item["applies_to"] != self.demographics.get("sex"):
                status[key] = ("na", None)     # a one-sex item: not on this patient's checklist
            elif parent:
                present = parent in listed and listed[parent]["polarity"] == "present"
                status[key] = ("default", item["absent_text"]) if present else ("na", None)
            elif key in self.open_items:
                status[key] = ("open", None)
            else:
                status[key] = ("no", item["absent_text"])
        return status

    def entries(self) -> dict:
        """Every id the analysis may name -> {"item", "text", "facts"}: the facts; for DDXPlus also the catalogue's
        recorded "no"s and defaults, and the checklist questions answered by the case's own facts (`answered_by`),
        whose id stands for those facts. "facts" is what `disclosed` reports for the id."""
        out = {f["id"]: {"item": f["item"], "text": f["text"], "facts": [f["id"]]} for f in self.facts}
        items = {i["key"]: i for i in self.catalogue}
        for key, (status, detail) in self.resolve_catalogue().items():
            if status in ("no", "default"):
                out[key] = {"item": items[key]["item"], "text": detail, "facts": [key]}
            elif status == "answered_by":
                out[key] = {"item": items[key]["item"], "text": " ".join(out[f]["text"] for f in detail),
                            "facts": list(detail)}
        return out


# ---------------------------------------------------------------- loading

def read_jsonl(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def release_dir(releases: Path, dataset: str, version: str | None = None) -> Path:
    """The release folder of a dataset: releases/<dataset>/<version>, or the only version folder there."""
    if version:
        folder = releases / dataset / version
        if not folder.is_dir():
            raise SystemExit(f"release {dataset} {version} not found in {releases}")
        return folder
    versions = sorted(p for p in (releases / dataset).iterdir() if p.is_dir())
    if len(versions) != 1:
        raise SystemExit(f"{dataset}: {len(versions)} release versions in {releases} "
                         f"({[p.name for p in versions]}); name one with --versions")
    return versions[0]


def parse_versions(text: str) -> dict:
    """ "medqa_cs=5eeb1bcf7230,ddxplus=b0e3fedac610" -> {dataset: version}."""
    return dict(pair.split("=", 1) for pair in text.split(",") if pair.strip())


def load_cases(eval_dir: Path, releases: Path, dataset: str, case_ids=None, version: str | None = None) -> list:
    """Load the cases of one dataset (all, or the given ids in the given order), with their anchors."""
    folder = release_dir(releases, dataset, version)
    patient_file = folder / f"{dataset}_patient.jsonl"
    version = hashlib.sha256(patient_file.read_bytes()).hexdigest()[:12]
    if version != folder.name:
        raise SystemExit(f"{patient_file}: SHA-256 prefix {version} does not match the release folder {folder.name}")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    catalogue = []
    if manifest.get("catalogue"):
        catalogue = json.loads((folder / manifest["catalogue"]).read_text(encoding="utf-8"))["items"]
    anchor_file = eval_dir / "anchors" / f"{dataset}.json"
    anchors = json.loads(anchor_file.read_text(encoding="utf-8")) if anchor_file.exists() else {}
    wanted = set(case_ids) if case_ids is not None else None
    cases = {}
    for row in read_jsonl(patient_file):
        if wanted is None or row["case_id"] in wanted:
            cases[row["case_id"]] = Case(
                case_id=row["case_id"], dataset=dataset, release=version, world=manifest["world"],
                demographics=row["demographics"], opening=row["opening"], facts=row["facts"],
                answered_by=row.get("answered_by", {}), catalogue=catalogue,
                open_items=tuple(manifest.get("open_world_items", ())), anchor=anchors.get(row["case_id"]))
    order = case_ids if case_ids is not None else list(cases)
    missing = [c for c in order if c not in cases]
    if missing:
        raise SystemExit(f"{dataset}: cases not in the release: {missing}")
    return [cases[c] for c in order]


def load_findings(releases: Path, dataset: str, version: str | None = None) -> dict:
    """The release's environment file: case id -> its findings (vital signs, examination findings, test results), each
    {"id", "kind", "name", "result", ...}, in record order."""
    path = release_dir(releases, dataset, version) / f"{dataset}_environment.jsonl"
    return {row["case_id"]: row["findings"] for row in read_jsonl(path)}


def study_ids(eval_dir: Path, dataset: str) -> list:
    """The ids of the study cases of a dataset (main/cases.json)."""
    listed = json.loads((eval_dir / "main" / "cases.json").read_text(encoding="utf-8"))["cases"][dataset]
    return [c["case_id"] for c in listed]


# ---------------------------------------------------------------- the record sheet

def person(demographics: dict) -> str:
    noun = {"female": "woman", "male": "man"}.get(demographics.get("sex"), "person")
    return f"{demographics['age']}-year-old {noun}"


def fact_line(fact: dict, indent: str = "") -> str:
    tags = []
    if fact.get("polarity") == "absent":
        tags.append("absent")
    if fact.get("time"):
        tags.append(TIME_TAGS[fact["time"]])
    if fact.get("complete"):
        tags.append("complete list")
    tag_part = f" ({', '.join(tags)})" if tags else ""
    return f'{indent}[{fact["id"]}] {fact["item"]}{tag_part}: "{fact["text"]}"'


HOW_TO_READ = (
    'Each line is one recorded entry: [id] what it is about (tags): "what the patient says". Indented lines are '
    'details of the entry above them. Tags: "absent" marks something the patient does not have or did not do; '
    '"now", "past", "recurrent" and "resolved" say when; "complete list" means the list in the text is all there is.')
OPEN_WORLD = (
    "This is an open record: it holds what is known about the patient. Anything it does not contain is not "
    "recorded: the patient does not know it or has not noticed it.")
CLOSED_WORLD = (
    "This is a closed record: it covers the clinic's whole checklist of symptoms, history and habits. The patient's "
    "own entries come first. Then come checklist questions that those entries answer, and then every other "
    'checklist item, each a recorded "no" with what the patient says. Anything that is on no checklist (for '
    "example, exactly when something started) is not recorded.")


def render_sheet(case: Case) -> str:
    """The record sheet (presentation P1)."""
    out = [f"PATIENT RECORD ({case.case_id})",
           f"Patient: {person(case.demographics)}.",
           f"Opening complaint (what the patient came in with): {', '.join(case.opening)}",
           "", HOW_TO_READ, CLOSED_WORLD if case.world == "closed" else OPEN_WORLD]
    status = case.resolve_catalogue()
    items = {i["key"]: i for i in case.catalogue}
    defaults = {}    # DDXPlus: parent fact id -> unlisted default children (catalogue items)
    for key, (state, _) in status.items():
        if state == "default":
            parent_fact = next(f for f in case.facts if f.get("key") == items[key]["parent"])
            defaults.setdefault(parent_fact["id"], []).append(items[key])
    children = {}
    for fact in case.facts:
        if "parent" in fact:
            children.setdefault(fact["parent"], []).append(fact)
    for category, heading in CATEGORIES.items():
        top = [f for f in case.facts if "parent" not in f and f["category"] == category]
        if not top:
            continue
        out += ["", heading.upper()]
        for fact in top:
            out.append(fact_line(fact))
            out += [fact_line(child, "    ") for child in children.get(fact["id"], [])]
            out += [f'    [{item["key"]}] {item["item"]} (absent, checklist default): "{item["absent_text"]}"'
                    for item in defaults.get(fact["id"], [])]
    answered = [(k, ids) for k, (state, ids) in status.items() if state == "answered_by"]
    if answered:
        texts = {f["id"]: f["text"] for f in case.facts}
        out += ["", "CHECKLIST QUESTIONS ANSWERED BY THE ENTRIES ABOVE (the checklist id stands for those entries)"]
        out += [f"[{k}] {items[k]['item']}: answered by {', '.join(ids)}: " + " ".join(f'"{texts[i]}"' for i in ids)
                for k, ids in answered]
    noes = [k for k, (state, _) in status.items() if state == "no"]
    if noes:
        out += ["", 'EVERY OTHER CHECKLIST ITEM: A RECORDED "NO"']
        for category, heading in CATEGORIES.items():
            keys = [k for k in noes if items[k]["category"] == category]
            if keys:
                out += ["", heading.upper()]
                out += [f'[{k}] {items[k]["item"]}: "{items[k]["absent_text"]}"' for k in keys]
    return "\n".join(out)
