import ast, sys
files = [
    r"app\config.py", r"app\db.py", r"app\main.py", r"app\services\config_service.py",
    r"app\services\health.py", r"app\models\base.py", r"app\models\chunk.py", r"app\models\queries.py",
    r"scripts\eval_retrieval.py",
    r"tests\conftest.py", r"tests\test_auth.py", r"tests\test_stats_api.py",
    r"tests\test_folder_service.py", r"tests\test_document_move.py", r"tests\test_document_api.py",
    r"tests\test_document_preview.py", r"tests\test_conversation_mode.py",
]
for f in files:
    ast.parse(open(f, encoding="utf-8").read())
print("all syntax ok")