"""A stub OpenAI-compatible server for plumbing tests without a GPU. It answers schema-forced calls with a valid
instance of the schema (sometimes a rule-breaking one, to exercise redrafts), doctor turns with canned questions, and
the final request with a canned differential. Every request is appended to a JSON-lines log for inspection. With
FAKE_LONG_CLOSINGS (a share, e.g. 0.5) that share of the doctor's closings is too long for the turn limit, a quarter of
them too long for the final's too, and a reply longer than max_tokens (about 4 characters a token) is cut, finish
reason "length".

    python tools/fake_server.py --port 8011 --log requests.jsonl
"""
import argparse
import hashlib
import json
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

QUESTIONS = ["When did this start, and has it changed since?", "Do you have any fever or chills?",
             "Does anything make it better or worse?", "Any other symptoms?",
             "Do you take any medicines, and do you have any medical conditions?",
             "I don't think it's anything serious. Do you smoke or drink?",
             "Has anyone in your family had similar problems?", "Can you tell me more about how you feel?"]
LONG_CLOSINGS = float(os.environ.get("FAKE_LONG_CLOSINGS") or 0)


def instance(schema: dict, rng: random.Random):
    if "enum" in schema:
        return rng.choice(schema["enum"])
    kind = schema.get("type")
    if kind == "object":
        props = schema["properties"]
        if "parts" in props and "facts" in props["parts"]["items"]["properties"]:     # the analysis schema
            ids = props["parts"]["items"]["properties"]["facts"]["items"]["enum"]
            bad = rng.random() < 0.2
            value = {"parts": [{"asks": "what the doctor asked", "facts": [] if bad else [rng.choice(ids)],
                                "answer": "from_record"},
                               {"asks": "a part the record does not answer", "facts": [],
                                "answer": "unrecorded_detail"}],
                     "volunteer": [], "worry_disputed": rng.random() < 0.3, "worry_asked": rng.random() < 0.2}
            if "open" in props:                     # the open field; sometimes an entry the rules refuse
                more = rng.random() < 0.4
                value["open"] = {"asks_for_more": more, "words": "any other symptoms?" if more else "",
                                 "area": "other symptoms" if more else "",
                                 "entries": [rng.choice(ids)] if more and rng.random() < 0.5 else []}
            if "reply" in props:
                value["reply"] = "Stub reply from the controller."
            for key in props:                       # a condition's decisions (sim/conditions.py)
                if key not in value:
                    value[key] = instance(props[key], rng)
            return value
        return {k: instance(v, rng) for k, v in props.items()}
    if kind == "array":
        return [instance(schema["items"], rng) for _ in range(schema.get("minItems", 0))]
    if kind == "boolean":
        return rng.random() < 0.5
    return "Stub text."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, value: dict) -> None:
        data = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send({"data": [{"id": "local", "root": "stub-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        with self.server.lock, open(self.server.log, "a", encoding="utf-8") as log:
            log.write(json.dumps(body, ensure_ascii=False) + "\n")
        messages = body["messages"]
        rng = random.Random(hashlib.sha256(json.dumps(messages).encode()).hexdigest())
        schema = (body.get("response_format") or {}).get("json_schema", {}).get("schema") or {}
        props = schema.get("properties", {})
        if "most_likely" in props:                 # the doctor's final assessment
            text = json.dumps({"most_likely": "Stub disease", "differential": ["Stub disease", "Other disease"],
                               "rationale": "Stub rationale."})
        elif schema and "action" not in props:     # a patient-side step
            text = json.dumps(instance(schema, rng))
        else:                                      # a doctor turn
            asked = sum(m["role"] == "assistant" for m in messages)
            finish = asked >= 5 and rng.random() < 0.3
            text = json.dumps({"action": "finish" if finish else "ask",
                               "message": "Thank you." if finish else QUESTIONS[asked % len(QUESTIONS)]})
            if "tests" in props["action"].get("enum", []) and rng.random() < 0.4:    # variant T: retrieve the findings
                text = json.dumps({"action": "tests", "message": ""})
            elif finish and LONG_CLOSINGS:        # a closing too long for the turn limit, per sample (seed)
                draw = random.Random(f"{body.get('seed')}|{json.dumps(messages)}").random()
                if draw < LONG_CLOSINGS:
                    size = 3000 if draw < LONG_CLOSINGS / 4 else 1800
                    text = json.dumps({"action": "finish", "message": ("My assessment. " * 200)[:size]})
        finish_reason = "stop"
        if LONG_CLOSINGS and len(text) > body.get("max_tokens", 10 ** 6) * 4:       # about 4 characters a token
            text, finish_reason = text[:body["max_tokens"] * 4], "length"
        prompt_chars = sum(len(m["content"]) for m in messages)
        self.send({"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
                   "usage": {"prompt_tokens": prompt_chars // 4, "completion_tokens": len(text) // 4}})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.log, server.lock = args.log, threading.Lock()
    print(f"stub server on http://127.0.0.1:{args.port}/v1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
