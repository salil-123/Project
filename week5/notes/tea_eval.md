# Tea / non-tea — Alpha Earth separability (test only)

Source: `manual_polygons.geojson` (169 polys, 60 px each).
Held-out by whole polygon (test_size=0.3). Model = StandardScaler->LinearSVC.

**Held-out accuracy: 0.934** on 3060 pixels.

```
              precision    recall  f1-score   support

         tea      0.938     0.961     0.950      1980
     non_tea      0.925     0.884     0.904      1080

    accuracy                          0.934      3060
   macro avg      0.932     0.923     0.927      3060
weighted avg      0.934     0.934     0.934      3060

confusion ['tea', 'non_tea']
[[1903   77]
 [ 125  955]]
```

Does NOT modify the hierarchy, base model, or catalogue — pure measurement of whether the embedding separates tea from non-tea before committing to a real split.
