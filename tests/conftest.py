"""Config global dos testes: desliga a thread de rastreio embutido."""
import os

os.environ["BRAWL_RASTREIO"] = "0"
