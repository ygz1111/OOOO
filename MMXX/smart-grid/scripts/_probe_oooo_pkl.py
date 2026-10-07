import pickle, glob, os

files = [
    r"C:\OOOO\OOOO\processed\step1_system_data.pkl",
    r"C:\OOOO\OOOO\processed\step2_cleaned_data.pkl",
    r"C:\OOOO\OOOO\processed\step4_engineered_data.pkl",
    r"C:\OOOO\OOOO\processed\step4_model_data.pkl",
    r"C:\OOOO\OOOO\processed\step5_normalized_data.pkl",
    r"C:\OOOO\OOOO\processed\step5_split_info.pkl",
]
for f in files:
    print("=" * 20, os.path.basename(f))
    try:
        with open(f, "rb") as fh:
            obj = pickle.load(fh)
        if hasattr(obj, "columns"):
            cols = [str(c) for c in obj.columns]
            print("type df", obj.shape)
            pv = [c for c in cols if any(k in c.lower() for k in ("pv", "solar", "光伏", "generat", "gen", "power", "output"))]
            print("PV-ish cols:", pv[:40])
            print("all cols head:", cols[:25])
        elif isinstance(obj, dict):
            print("dict keys:", list(obj.keys())[:30])
        elif hasattr(obj, "keys"):
            print("type", type(obj).__name__, "len", len(obj))
        else:
            print("type", type(obj).__name__, "len", len(obj))
    except Exception as e:
        print("ERR", type(e).__name__, e)
