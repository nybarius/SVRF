import BraidedTrain.Landing

/-!
# BraidedTrain.Retarget — moving a stacked pull request's base changes only the base

A stacked pull request is based on its parent's branch. `Daemon.stacked` waits while the
parent is open and, once the parent has merged, retargets the pull request to the base
branch (`retarget`): one API call that changes the base ref and nothing else. The tree a
pull request lands is the merge step of its head onto the tree its base ref holds
(`landsOn`). Finite data, no Mathlib.

1. `retarget_head`, `retarget_headTree`: the head, and so the tree the head branch holds,
   is unchanged by a retarget.
2. `retarget_landsOn`: after a retarget the pull request lands its head onto the new base,
   exactly as if it had been opened against it; `retarget_fold`: the same for a stack of
   pull requests folded onto the new base.
3. `retarget_lands_same`: when the new base holds the same tree as the old one, the landed
   tree does not change at all. `retarget_after_parent`: this is the case after a parent
   landed by a replayed landing (the per-merge tree check) of a family whose gated tree is
   the tree the parent branch held — the base branch then holds exactly that tree, so the
   stacked pull request lands the tree it would have landed on its parent.

Modelling boundary: that GitHub's base change touches no commit is GitHub's behaviour, not
a theorem here; the train re-reads the head sha before every merge (`HEAD_MOVED`) and the
landed tree after it, so a retarget that did move the head is caught, not assumed away.
-/

namespace BraidedTrain

/-- A pull request: its head and the ref it is based on. -/
structure Pull (Ref Head : Type) where
  head : Head
  base : Ref

variable {Ref Head Tree : Type}

/-- Change the base ref only. -/
def retarget (p : Pull Ref Head) (r : Ref) : Pull Ref Head :=
  { p with base := r }

/-- The tree a pull request lands: its head stepped onto the tree its base ref holds. -/
def landsOn (refs : Ref → Tree) (step : Tree → Head → Option Tree) (p : Pull Ref Head) :
    Option Tree :=
  step (refs p.base) p.head

theorem retarget_head (p : Pull Ref Head) (r : Ref) : (retarget p r).head = p.head := rfl

theorem retarget_base (p : Pull Ref Head) (r : Ref) : (retarget p r).base = r := rfl

/-- The head branch's tree is unchanged by a retarget. -/
theorem retarget_headTree (headTree : Head → Tree) (p : Pull Ref Head) (r : Ref) :
    headTree (retarget p r).head = headTree p.head := rfl

/-- After a retarget, the pull request lands its head onto the new base. -/
theorem retarget_landsOn (refs : Ref → Tree) (step : Tree → Head → Option Tree)
    (p : Pull Ref Head) (r : Ref) :
    landsOn refs step (retarget p r) = step (refs r) p.head := rfl

/-- Retargeting a stack leaves every head as it was. -/
theorem retarget_heads (r : Ref) : ∀ ps : List (Pull Ref Head),
    (ps.map (fun p => retarget p r)).map Pull.head = ps.map Pull.head
  | [] => rfl
  | _ :: ps => by
    simp only [List.map_cons]
    rw [retarget_heads r ps]
    rfl

/-- A stack retargeted to a new base folds its unchanged heads onto that base. -/
theorem retarget_fold (step : Tree → Head → Option Tree) (t : Tree) (r : Ref)
    (ps : List (Pull Ref Head)) :
    fold step t ((ps.map (fun p => retarget p r)).map Pull.head) = fold step t (ps.map Pull.head) := by
  rw [retarget_heads]

/-- A new base holding the same tree lands the same tree. -/
theorem retarget_lands_same (refs : Ref → Tree) (step : Tree → Head → Option Tree)
    (p : Pull Ref Head) (r : Ref) (h : refs r = refs p.base) :
    landsOn refs step (retarget p r) = landsOn refs step p := by
  rw [retarget_landsOn, h]
  rfl

/-- After the parent's family landed by a replayed landing, the base branch holds the
parent's gated tree; if that is the tree the parent branch held, retargeting the stacked
pull request to the base branch changes nothing it lands. -/
theorem retarget_after_parent (refs : Ref → Tree) (step : Tree → Head → Option Tree)
    (p : Pull Ref Head) (main : Ref) {base g : Tree} {hs : List Head} {L : List (Head × Tree)}
    (hg : fold step base hs = some g) (hr : Replays step base L) (hl : L.map Prod.fst = hs)
    (hmain : refs main = landed base L) (hparent : refs p.base = g) :
    landsOn refs step (retarget p main) = landsOn refs step p := by
  apply retarget_lands_same
  rw [hmain, hparent]
  exact landed_eq_gated step hg hr hl

end BraidedTrain
