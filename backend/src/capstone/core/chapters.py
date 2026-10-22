"""The single, flat catalog; database access belongs to services.chapters."""

CHAPTERS = (
    ("complexity", "绪论与算法分析", 10),
    ("linear-list", "线性表", 20),
    ("stack-queue", "栈与队列", 30),
    ("strings-arrays", "串、数组与广义表", 40),
    ("tree", "树与二叉树", 50),
    ("graph", "图", 60),
    ("search", "查找", 70),
    ("sort", "排序", 80),
)
CHAPTER_CODES = tuple(code for code, _, _ in CHAPTERS)
