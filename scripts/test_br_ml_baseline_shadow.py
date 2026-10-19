"""No external ML dependency; baseline cannot fit on holdout labels."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.ml_baseline_shadow import train,predict,evaluate

def test_fit_and_holdout_brier():
    rows=[{"features":{"volume_ratio":float(i)},"label":"TP3" if i>=5 else "SL"}
          for i in range(10)]
    model=train(rows,feature="volume_ratio",threshold=5)
    assert model["probabilities"]["high"]>model["probabilities"]["low"]
    assert model["counts"]=={"low":5,"high":5}
    result=evaluate(model,rows)
    assert result["n"]==10 and result["improvement"]>0

def test_unseen_features_fallback_to_train_base():
    rows=[{"features":{"volume_ratio":1},"label":"SL"},
          {"features":{"volume_ratio":2},"label":"TP3"}]
    model=train(rows,feature="volume_ratio",threshold=1.5)
    assert predict(model,{"features":{}})==model["base_rate"]
    assert evaluate(model,[])["improvement"] is None

def test_invalid_feature_is_rejected():
    try:
        train([{"features":{"volume_ratio":2},"label":"TP3"}],
              feature="future_price",threshold=1)
        assert False
    except ValueError:
        pass

if __name__=="__main__":
    for name,fn in sorted(globals().copy().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok",name)
