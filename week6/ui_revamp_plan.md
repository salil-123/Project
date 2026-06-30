# Week-6 UI revamp — task breakdown

Five issues raised after inspecting the live app. Mostly frontend (`static/{index.html,
app.js,style.css}`), one small backend touch for #3. Tracking the full picture here so the
context survives.

## 1. Merges live on the hierarchy + pick merge sources from the tree
- Show each active merge **inside the hierarchy tree**: source leaves get a `→ <target>` tag in
  the merge colour, and each merge target shows as a virtual node at the bottom of the tree
  (swatch + `← sources` + ✕ remove).
- Pick merge sources **by ticking leaves in the tree** (checkbox on each leaf), not a separate
  list. `doMerge` reads the ticked leaves.
- Drop the separate `#mergeLeaves` checkbox list and `#mergeList` panel; fold both into the tree.
- State: `MERGES` (rules) + `mergeSel` (Set of ticked leaf ids), `loadMerges()` feeds renderTree.

## 2. Move year + base picker out of the sidebar; onboard via the zoo
- Remove the **Inference year** control from above Run classification.
- Remove the whole **🧭 Base classes** sidebar section (base is now chosen in the zoo by
  applying a base model card — already works via `/api/apply` → `_switch_base`).
- Year for Alpha Earth lives **in the zoo**, on the Alpha Earth inference dataset card detail.
  A client-side `inferYear` (localStorage) drives Run classification; Detailed still forces 2024.
- On first open, auto-open the zoo so the user picks base classes first (localStorage `onboarded`
  flag, set when they close/apply so returning users aren't forced).

## 3. Dataset public link via the detail pane (not at publish time)
- Add a "Public source link" input + save on the **dataset card detail pane**; saves to the
  card's `source_url`. Backend: `AnnotateIn.source_url` + `update_card_meta` stores it.
- Stop prompting for a link per dataset at publish (`askDatasetLinks` removed from publish flow).

## 4. "Data so far" should respond to the selected class + hide when irrelevant
- The split distribution is shared by siblings (tea/non_tea), so it looked stuck. Highlight the
  **currently selected** sibling row and title it with the parent split, so switching tea↔non_tea
  visibly updates. Keep hiding it when there's no split / no data / root.

## 5. Widen the sidebar
- `--sidebar` 320px → 360px (sidebar width + toast centering use the var).
