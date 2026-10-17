from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
CORPUS.mkdir(parents=True, exist_ok=True)

A = """The instrument drifted by 0.4 degrees during the second run.
The drift was corrected after recalibration on day three.
No samples were lost, but the first twelve readings were excluded.
"""
B = """Recalibration reduced the mean offset from 0.4 to 0.05 degrees.
The same twelve readings were re-measured and agreed with the corrected series.
"""
# Chinese deliberately: a GB18030 file whose bytes are valid UTF-8 would not
# exercise the encoding-fallback path at all.
C = """第三次传感器故障后更换了探头。
更换之前的日志在归档中缺失。
"""

(CORPUS / "run_a.txt").write_text(A, encoding="utf-8")
(CORPUS / "run_a_copy.txt").write_text(A, encoding="utf-8")
(CORPUS / "run_b.txt").write_text(B, encoding="utf-8")
(CORPUS / "run_c.txt").write_text(C, encoding="utf-8")
(CORPUS / "run_c_gbk.txt").write_text(C, encoding="gb18030")
(CORPUS / "empty.txt").write_text("", encoding="utf-8")
print("wrote", CORPUS, "files:", len(list(CORPUS.iterdir())))
