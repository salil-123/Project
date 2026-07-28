# #13 — Representing a decision tree in our framework

Sir's ask: take the "Beyond Flat Classifiers" hierarchical decision tree (Bansal et al., the
CoRE-stack LULC paper) and show our framework can *represent* it — including the awkward move
where a rule reassigns pixels across branches (e.g. "if a crop pixel has slope > x, it's actually
shrub"), so we split crop into crop′/shrub′ and then **merge shrub′ back into the shrub branch**.

## The four primitives, and what each is

Our framework already has exactly four tree-mutating primitives, and together they express any
finite decision tree over the pixel:

| Primitive | What it does | Resolver kind | Where |
|-----------|--------------|---------------|-------|
| **Split** (model) | divide a class into children learned from example polygons | trained linear model (`data/refine/<node>.joblib`) | `refine.split_op` |
| **Rule split** (#12) | divide a class by an interpretable threshold on indices | an expression, no training (`node.rule`) | `refine.rule_split_op` |
| **Add** | introduce one new class under a node; the rest of that node stays as an auto residual class | the same per-node trainer (an ADD is a split whose other child keeps the parent's identity) | `refine.add_class_op` |
| **Merge** (#9) | relabel chosen leaves — even from different branches — into one class | a post-inference relabel layer (`merge_rules.json`) | `merges.add` |

A node's children are resolved by **either** a model **or** a rule; inference composites them
identically (`infer._refine_idx` dispatches on `features == "rule"`), and merges run *after* all
resolvers in both the EE-tile path (`_merge_ee`) and the point path (`_apply_merges`). That
ordering is what makes cross-branch reassignment possible: a resolver can only push a pixel *down*
its own subtree, but a merge can pull a leaf from anywhere into a new class.

## Expressivity claim

**Split + rule-split + add + merge ⇒ any finite decision tree over the pixel.**
- Internal decision nodes = splits (learned boundary) or rule splits (hand-set boundary on an
  index). A node may test a *different* feature from its parent — model on embeddings here, NDVI
  threshold there, slope threshold below — which is precisely the paper's "each sub-task gets its
  own feature vector + method".
- **Add** is how the tree grows *incrementally* rather than by re-partitioning: it carves one new
  class out of a node and leaves the remainder as a residual child, so you can extend a taxonomy
  without restating every sibling or retraining the whole level. (Mechanically an ADD is a split
  whose second child inherits the parent's identity, which is why it reuses the same trainer.)
- Leaves that the tree structure separates but the taxonomy wants *unified* (the same final class
  reached by two different paths) = a merge. This is the one thing a pure top-down tree can't do,
  and it's why the paper needs post-classification refinement.

## The crop → shrub worked example

Goal: within greenery, a crop pixel on steep terrain should end up labelled **shrub**, not crop.

```
greenery
├─ (split, model)  crop_shrub → crop, shrub
│                                 │
│                                 └─ (rule split on crop)  slope > 15 → shrub_prime, else → crop_prime
└─ ...
merge:  shrub_prime  →  shrub          # reassign the steep "crops" back to the shrub class
```

Steps, all live in the app:
1. Split `greenery` into `crop` / `shrub` (model split on your polygons), retrain.
2. **Rule split** `crop` with `slope > 15 → shrub_prime`, default `crop_prime` (#12). No training —
   it renders as tiles immediately.
3. **Merge** `shrub_prime` into `shrub` (#9). Now steep "crop" pixels carry the shrub label.

The net effect is a decision tree whose crop branch has a terrain gate that hands part of its
output to the shrub branch — exactly the paper's targeted refinement, built from our three
primitives with no new machinery.

## Verified

A live run on the IIT box (rule-split greenery by `ndvi_annual > 0.3`, then merge the
`sparse_veg` rule-child with base `barren` into `open_land`) rendered as crisp EE tiles with the
merged class present and both sources gone — confirming a rule-split child is a first-class merge
source and the composition holds end-to-end. The crop→shrub shape is the same graph with a
`slope` rule in place of the NDVI one.
