import importlib.util
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock
from contextlib import closing


MODULE_PATH = pathlib.Path(__file__).with_name("gpu45-responses-proxy.py")
SPEC = importlib.util.spec_from_file_location("gpu45_responses_proxy", MODULE_PATH)
PROXY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROXY)


class NamespaceToolTranslationTests(unittest.TestCase):
    def tearDown(self):
        PROXY.cancel_llm_idle_unload()

    @mock.patch.object(PROXY.subprocess, "run")
    def test_idle_unload_stops_provider_for_current_generation(self, run):
        PROXY.cancel_llm_idle_unload()
        generation = PROXY.LLM_IDLE_GENERATION

        PROXY.unload_llm_after_idle(generation)

        run.assert_called_once_with(["systemctl", "stop", PROXY.PROVIDER_SERVICE], check=False, timeout=30)

    @mock.patch.object(PROXY.subprocess, "run")
    def test_stale_idle_unload_does_not_stop_provider(self, run):
        stale_generation = PROXY.LLM_IDLE_GENERATION
        PROXY.cancel_llm_idle_unload()

        PROXY.unload_llm_after_idle(stale_generation)

        run.assert_not_called()

    def test_flattens_namespace_tools_and_preserves_regular_tools(self):
        body = {
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__node_repl__",
                    "description": "Node REPL tools.",
                    "tools": [
                        {
                            "type": "function",
                            "name": "js",
                            "description": "Run JavaScript.",
                            "strict": False,
                            "parameters": {"type": "object"},
                        }
                    ],
                },
                {"type": "function", "name": "shell_command", "parameters": {}},
            ]
        }

        normalized, name_map = PROXY.flatten_namespace_tools(body)

        self.assertEqual(
            [tool["name"] for tool in normalized["tools"]],
            ["mcp__node_repl__js", "shell_command"],
        )
        self.assertEqual(
            name_map["mcp__node_repl__js"],
            ("mcp__node_repl__", "js"),
        )
        self.assertIn("Node REPL tools.", normalized["tools"][0]["description"])
        self.assertEqual(body["tools"][0]["type"], "namespace")

    def test_restores_namespaced_calls_recursively(self):
        event = {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "type": "function_call",
                        "name": "mcp__node_repl__js",
                        "call_id": "call_1",
                        "arguments": "{}",
                    }
                ]
            },
        }

        restored = PROXY.restore_namespaced_calls(
            event, {"mcp__node_repl__js": ("mcp__node_repl__", "js")}
        )

        call = restored["response"]["output"][0]
        self.assertEqual(call["namespace"], "mcp__node_repl__")
        self.assertEqual(call["name"], "js")

    def test_inlines_nested_local_schema_definitions(self):
        body = {
            "tools": [
                {
                    "type": "function",
                    "name": "search_properties",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "request": {
                                "type": "object",
                                "properties": {
                                    "bedrooms": {"$ref": "#/$defs/MinMaxInt"},
                                    "location": {"$ref": "#/$defs/LatLong"},
                                },
                                "$defs": {
                                    "MinMaxInt": {
                                        "type": "object",
                                        "properties": {
                                            "min": {"type": "integer"},
                                            "max": {"type": "integer"},
                                        },
                                    },
                                    "LatLong": {
                                        "type": "object",
                                        "properties": {
                                            "latitude": {"type": "number"},
                                            "longitude": {"type": "number"},
                                        },
                                    },
                                },
                            }
                        },
                    },
                }
            ]
        }

        normalized, count = PROXY.normalize_tool_schemas(body)

        request = normalized["tools"][0]["parameters"]["properties"]["request"]
        self.assertEqual(count, 2)
        self.assertEqual(request["properties"]["bedrooms"]["type"], "object")
        self.assertEqual(request["properties"]["location"]["type"], "object")
        self.assertNotIn("$defs", request)
        self.assertIn("$defs", body["tools"][0]["parameters"]["properties"]["request"])

    def test_breaks_recursive_local_schema_cycle_without_mutating_input(self):
        schema = {
            "type": "object",
            "properties": {"node": {"$ref": "#/$defs/Node"}},
            "$defs": {
                "Node": {
                    "type": "object",
                    "properties": {"next": {"$ref": "#/$defs/Node"}},
                }
            },
        }

        normalized, count = PROXY.normalize_local_schema_refs(schema)

        self.assertEqual(count, 2)
        self.assertEqual(normalized["properties"]["node"]["properties"]["next"], {})
        self.assertIn("$defs", schema)

    def test_builds_structured_followup_and_flattens_prior_call(self):
        PROXY.RESPONSE_STORE.clear()
        PROXY.RESPONSE_STORE["resp_1"] = {
            "stored_at": 0,
            "request": {"input": "Run 1+1."},
            "response": {
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "function_call",
                        "namespace": "mcp__node_repl__",
                        "name": "js",
                        "call_id": "call_1",
                        "arguments": "{\"code\":\"1+1\"}",
                    },
                ]
            },
        }
        body = {
            "previous_response_id": "resp_1",
            "input": [
                {"type": "function_call_output", "call_id": "call_1", "output": "2"}
            ],
        }

        followup = PROXY.build_followup_input(body)
        flattened = PROXY.flatten_namespaced_calls(
            followup, {"mcp__node_repl__js": ("mcp__node_repl__", "js")}
        )

        self.assertEqual([item["type"] for item in flattened], ["message", "function_call", "function_call_output"])
        self.assertEqual(flattened[1]["name"], "mcp__node_repl__js")
        self.assertNotIn("namespace", flattened[1])

    def test_moves_tool_result_images_to_user_message(self):
        tool_output = [
            {
                "type": "function_call_output",
                "call_id": "call_image",
                "output": [
                    {"type": "input_text", "text": "Screenshot captured."},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,AAAA",
                        "detail": "high",
                    },
                ],
            }
        ]

        normalized = PROXY.normalize_tool_output_items(tool_output)

        self.assertEqual(normalized[0]["output"], "Screenshot captured.")
        self.assertEqual(normalized[1]["type"], "message")
        self.assertEqual(normalized[1]["role"], "user")
        self.assertEqual(normalized[1]["content"][1]["type"], "input_image")
        self.assertEqual(
            normalized[1]["content"][1]["image_url"],
            "data:image/png;base64,AAAA",
        )

    def test_moves_late_system_and_developer_messages_to_front(self):
        request_input = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Earlier user text."}],
            },
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "done",
            },
            {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": "System rules."}],
            },
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "Developer rules."}],
            },
        ]

        normalized = PROXY.normalize_system_messages(request_input)

        self.assertEqual(normalized[0]["role"], "system")
        self.assertIn("System rules.", normalized[0]["content"][0]["text"])
        self.assertIn("developer:\nDeveloper rules.", normalized[0]["content"][0]["text"])
        self.assertEqual([item.get("role") for item in normalized[1:] if item.get("type") == "message"], ["user"])
        self.assertEqual(normalized[2]["type"], "function_call_output")

    def test_moves_top_level_instructions_into_input_system_message(self):
        body = {
            "instructions": "Follow repository evidence.",
            "input": "List my skills.",
        }

        normalized = PROXY.normalize_responses_instructions(body)

        self.assertNotIn("instructions", normalized)
        self.assertEqual(normalized["input"][0]["role"], "system")
        self.assertEqual(normalized["input"][0]["content"][0]["text"], "Follow repository evidence.")
        self.assertEqual(normalized["input"][1]["role"], "user")
        self.assertEqual(normalized["input"][1]["content"][0]["text"], "List my skills.")

    def test_combines_top_level_and_late_system_instructions(self):
        body = {
            "instructions": "Top level rules.",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Earlier user text."}],
                },
                {
                    "type": "message",
                    "role": "system",
                    "content": [{"type": "input_text", "text": "Late system rules."}],
                },
            ],
        }

        with_top_level = PROXY.normalize_responses_instructions(body)
        normalized = PROXY.normalize_system_messages(with_top_level["input"])

        self.assertEqual(normalized[0]["role"], "system")
        self.assertIn("Top level rules.", normalized[0]["content"][0]["text"])
        self.assertIn("Late system rules.", normalized[0]["content"][0]["text"])
        self.assertEqual(normalized[1]["role"], "user")

    def test_stops_fifth_identical_tool_call(self):
        history = []
        for index in range(5):
            history.extend(
                [
                    {
                        "type": "function_call",
                        "name": "shell_command",
                        "call_id": f"call_{index}",
                        "arguments": '{"command":"same command"}',
                    },
                    {
                        "type": "function_call_output",
                        "call_id": f"call_{index}",
                        "output": "done",
                    },
                ]
            )

        guarded, event = PROXY.apply_tool_loop_guard(
            {"input": history, "tools": [{"type": "function", "name": "shell_command"}]}
        )

        self.assertEqual(event, {"name": "shell_command", "count": 5})
        self.assertEqual(guarded["tools"], [])
        self.assertFalse(guarded["parallel_tool_calls"])
        self.assertIn("Provider safety stop", guarded["input"][-1]["content"][0]["text"])

    def test_allows_four_identical_tool_calls(self):
        history = [
            {"type": "function_call", "name": "edit", "arguments": "{}"}
            for _ in range(4)
        ]

        original = {"input": history, "tools": [{"type": "function", "name": "edit"}]}
        guarded, event = PROXY.apply_tool_loop_guard(original)

        self.assertIs(guarded, original)
        self.assertIsNone(event)

    def test_exempts_wait_polling(self):
        history = [
            {"type": "function_call", "name": "functions__wait", "arguments": "{}"}
            for _ in range(20)
        ]

        guarded, event = PROXY.apply_tool_loop_guard({"input": history, "tools": []})

        self.assertIsNone(event)
        self.assertEqual(len(guarded["input"]), 20)


class EndpointControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_db = PROXY.DB_PATH
        self.previous_profile = PROXY.PROFILE_PATH
        PROXY.DB_PATH = str(pathlib.Path(self.temporary.name) / "test.db")
        PROXY.PROFILE_PATH = str(pathlib.Path(self.temporary.name) / "profile.json")
        with closing(sqlite3.connect(PROXY.DB_PATH)) as db:
            db.executescript("""
                CREATE TABLE EndpointSetting (id TEXT PRIMARY KEY, allowAnonymous INTEGER, updatedAt TEXT);
                INSERT INTO EndpointSetting VALUES ('default', 1, CURRENT_TIMESTAMP);
                CREATE TABLE ApiKey (id TEXT PRIMARY KEY, name TEXT, keyHash TEXT, keyPrefix TEXT, expiresAt TEXT, suspendedAt TEXT, lastUsedAt TEXT, requestCount INTEGER, promptTokens INTEGER, completionTokens INTEGER, createdAt TEXT);
                CREATE TABLE ApiKeyUsage (id TEXT PRIMARY KEY, apiKeyId TEXT, model TEXT, requestedModel TEXT, promptTokens INTEGER, completionTokens INTEGER, statusCode INTEGER, createdAt TEXT);
                CREATE TABLE ModelAsset (path TEXT PRIMARY KEY, name TEXT, servedAlias TEXT, defaultModel INTEGER, active INTEGER, served INTEGER, draftPath TEXT, projectorPath TEXT);
                CREATE TABLE LaunchProfile (
                    modelPath TEXT,
                    modelDraftPath TEXT,
                    mmprojPath TEXT,
                    host TEXT,
                    port INTEGER,
                    ctxSize INTEGER,
                    gpuLayers TEXT,
                    batchSize INTEGER,
                    uBatchSize INTEGER,
                    cacheRamMiB INTEGER,
                    cacheTypeK TEXT,
                    cacheTypeV TEXT,
                    cacheReuse INTEGER,
                    specType TEXT,
                    specDraftNMax INTEGER,
                    flashAttention TEXT,
                    backend TEXT DEFAULT 'rocm',
                    serverBinary TEXT,
                    runtimeLibraryPath TEXT,
                    fanBoostOnBusy INTEGER DEFAULT 0,
                    imageMinTokens INTEGER,
                    metrics INTEGER,
                    jinja INTEGER,
                    active INTEGER,
                    updatedAt TEXT
                );
            """)

    def tearDown(self):
        PROXY.DB_PATH = self.previous_db
        PROXY.PROFILE_PATH = self.previous_profile
        self.temporary.cleanup()

    def test_models_exclude_mtp_and_projectors(self):
        with closing(sqlite3.connect(PROXY.DB_PATH)) as db:
            db.executemany(
                "INSERT INTO ModelAsset VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)",
                [
                    ("/models/qwen.gguf", "qwen.gguf", "qwen", 1, 1, 1),
                    ("/models/mtp-qwen.gguf", "mtp-qwen.gguf", "mtp", 0, 0, 1),
                    ("/models/main-mtp-model.gguf", "main-mtp-model.gguf", "main-mtp", 0, 0, 1),
                    ("/models/mmproj.gguf", "mmproj.gguf", "projector", 0, 0, 1),
                ],
            )
            db.commit()
        self.assertEqual([model["servedAlias"] for model in PROXY.visible_models()], ["qwen", "main-mtp"])

    def test_unknown_model_falls_back_to_active(self):
        pathlib.Path(PROXY.PROFILE_PATH).write_text('{"modelPath":"/models/qwen.gguf"}', encoding="utf-8")
        with closing(sqlite3.connect(PROXY.DB_PATH)) as db:
            db.execute("INSERT INTO ModelAsset VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)", ("/models/qwen.gguf", "qwen.gguf", "qwen", 0, 1, 0))
            db.commit()
        self.assertEqual(PROXY.resolve_model("not-installed")["servedAlias"], "qwen")

    def test_uses_persisted_cross_directory_companions(self):
        with closing(sqlite3.connect(PROXY.DB_PATH)) as db:
            db.execute(
                "INSERT INTO ModelAsset VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("/models/main/qwen.gguf", "qwen.gguf", "qwen", 1, 1, 1, "/models/draft/mtp.gguf", "/models/vision/mmproj.gguf"),
            )
            db.commit()
        with PROXY.db_connect() as db:
            draft, projector = PROXY.model_companions(db, "/models/main/qwen.gguf")
        self.assertEqual(draft, "/models/draft/mtp.gguf")
        self.assertEqual(projector, "/models/vision/mmproj.gguf")

    def test_model_metadata_uses_launch_profile_context_window(self):
        with closing(sqlite3.connect(PROXY.DB_PATH)) as db:
            db.execute(
                "INSERT INTO ModelAsset VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)",
                ("/models/qwythos.gguf", "qwythos.gguf", "Qwythos-9B", 1, 1, 1),
            )
            db.execute(
                """
                INSERT INTO LaunchProfile (
                    modelPath, modelDraftPath, mmprojPath, host, port, ctxSize,
                    gpuLayers, batchSize, uBatchSize, cacheRamMiB, cacheTypeK,
                    cacheTypeV, cacheReuse, specType, specDraftNMax,
                    flashAttention, imageMinTokens, metrics, jinja, active,
                    updatedAt
                ) VALUES (?, NULL, NULL, '0.0.0.0', 30000, ?, 'all', 4096, 1024,
                    16384, 'q4_0', 'q4_0', 1024, 'draft-mtp', 2, 'on',
                    1024, 1, 1, 1, CURRENT_TIMESTAMP)
                """,
                ("/models/qwythos.gguf", 1048576),
            )
            db.commit()

        metadata = PROXY.model_metadata(
            {"path": "/models/qwythos.gguf", "servedAlias": "Qwythos-9B"}
        )

        self.assertEqual(metadata["id"], "Qwythos-9B")
        self.assertEqual(metadata["context_window"], 1048576)
        self.assertEqual(metadata["max_context_window"], 1048576)

    def test_applies_saved_launch_profile_settings(self):
        with closing(sqlite3.connect(PROXY.DB_PATH)) as db:
            db.execute(
                """
                INSERT INTO LaunchProfile (
                    modelPath, modelDraftPath, mmprojPath, host, port, ctxSize,
                    gpuLayers, batchSize, uBatchSize, cacheRamMiB, cacheTypeK,
                    cacheTypeV, cacheReuse, specType, specDraftNMax,
                    flashAttention, imageMinTokens, metrics, jinja, active,
                    updatedAt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    "/models/qwen.gguf",
                    None,
                    "/models/mmproj.gguf",
                    "0.0.0.0",
                    30000,
                    262144,
                    "all",
                    4096,
                    1024,
                    16384,
                    "q4_0",
                    "q4_0",
                    1024,
                    "draft-mtp",
                    2,
                    "on",
                    1024,
                    1,
                    1,
                    1,
                ),
            )
            db.commit()

        with PROXY.db_connect() as db:
            launch_profile = PROXY.model_launch_profile(db, "/models/qwen.gguf")
        profile = {"batchSize": 2048, "uBatchSize": 512, "metrics": False, "jinja": False}

        PROXY.apply_launch_profile_settings(profile, launch_profile)

        self.assertEqual(profile["batchSize"], 4096)
        self.assertEqual(profile["uBatchSize"], 1024)
        self.assertEqual(profile["backend"], "rocm")
        self.assertFalse(profile["fanBoostOnBusy"])
        self.assertTrue(profile["metrics"])
        self.assertTrue(profile["jinja"])

    def test_managed_key_authentication_and_usage(self):
        raw_key = "gpu45_test"
        with closing(sqlite3.connect(PROXY.DB_PATH)) as db:
            db.execute(
                "INSERT INTO ApiKey VALUES (?, ?, ?, ?, NULL, NULL, NULL, 0, 0, 0, CURRENT_TIMESTAMP)",
                ("key-1", "test", PROXY.hashlib.sha256(raw_key.encode()).hexdigest(), "gpu45_test..."),
            )
            db.commit()
        key, error = PROXY.authenticate({"Authorization": f"Bearer {raw_key}"})
        self.assertIsNone(error)
        self.assertEqual(key["id"], "key-1")
        PROXY.record_usage("key-1", "qwen", "qwen", 200, {"usage": {"input_tokens": 10, "output_tokens": 5}})
        with closing(sqlite3.connect(PROXY.DB_PATH)) as db:
            totals = db.execute("SELECT requestCount, promptTokens, completionTokens FROM ApiKey WHERE id = 'key-1'").fetchone()
        self.assertEqual(totals, (1, 10, 5))

    def test_anonymous_mode_accepts_unknown_bearer_key(self):
        key, error = PROXY.authenticate({"Authorization": "Bearer client-placeholder-key"})
        self.assertIsNone(key)
        self.assertIsNone(error)

    def test_required_key_mode_rejects_unknown_bearer_key(self):
        with closing(sqlite3.connect(PROXY.DB_PATH)) as db:
            db.execute("UPDATE EndpointSetting SET allowAnonymous = 0 WHERE id = 'default'")
            db.commit()

        key, error = PROXY.authenticate({"Authorization": "Bearer client-placeholder-key"})

        self.assertIsNone(key)
        self.assertEqual(error, "Invalid API key")


if __name__ == "__main__":
    unittest.main()
