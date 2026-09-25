/-!
# BraidedTrain.Families — the enumeration is sound and complete; the kept family is maximum

`svrf.rules.families` enumerates the maximal pairwise-compatible sets of pull requests with
Bron–Kerbosch and pivoting: `extend(R, P, X)` reports `R` when `P` and `X` are both empty;
otherwise it picks a pivot `u` from `P ∪ X` and, for each `v` of `P` not compatible with
`u` (in sorted order, the list computed once), recurses on `(R ∪ {v}, P ∩ N(v), X ∩ N(v))`
and then moves `v` from `P` to `X`. `choose_families` keeps the first family of the sorted
list. `bk` below is that recursion; the pivot and the iteration order are left arbitrary
(any function), so the result covers the code's choices. Finite lists, no Mathlib.

1. `bk_maximal`: under a symmetric compatibility relation, every set `bk` reports from
   `R = [], P = nodes, X = []` is pairwise compatible, drawn from the nodes, and maximal:
   every node left out is incompatible with some member (`Maximal`).
2. `conflictCompat` is the relation `families` builds from the conflict edges (distinct and
   not joined by an edge); `conflictCompat_symm` shows it is symmetric.
   `chosen_family_maximal`: every family the enumeration reports, so in particular the one
   `choose_families` keeps, holds no conflicting pair, and every pull request left out has
   a conflict edge to a kept one — the `with` list `choose_families` reports for it is
   never empty.
3. Completeness. `bk_complete`: with a pivot drawn from `P ∪ X` (`codePivot_mem`: the
   code's rule, the node of `P ∪ X` with the most compatible candidates, is one) and an
   iteration order that visits exactly the nodes of its list (the code's `sorted`), every
   maximal compatible set is reported, given depth above its size. The pivot argument is
   the textbook one: if no member of `M` outside `R` were a non-neighbour of the pivot `u`,
   then `u` would be compatible with all of `M` (the members in `R` because `u` is a
   candidate or excluded, the rest by assumption) yet outside it, against maximality.
   `grow_maximal`: every compatible set extends greedily to a maximal one containing it.
4. `chosen_family_maximum`: so the first family of the size-sorted list, the one
   `choose_families` keeps, is a maximum compatible set: no duplicate-free compatible set
   of the same candidates is larger (`bk_nodup`: the reported families have no duplicates,
   so a family's length is its size).

Depth: `bk` takes a depth bound so that Lean sees it terminate; soundness holds at every
bound, completeness at any bound above the number of candidates. The code's recursion is
unbounded and terminates because `P` loses `v` at each level, so it reaches the same
results.
-/

namespace BraidedTrain

section BronKerbosch
variable {V : Type} [DecidableEq V] (compat : V → V → Bool)

/-- Pairwise compatible. -/
def Clique (R : List V) : Prop :=
  ∀ a ∈ R, ∀ b ∈ R, a ≠ b → compat a b = true

/-- A compatible set drawn from `U` that no node of `U` outside it can join. -/
def Maximal (U R : List V) : Prop :=
  Clique compat R ∧ (∀ a ∈ R, a ∈ U) ∧ ∀ w ∈ U, w ∉ R → ∃ a ∈ R, compat a w = false

/-- The loop over the non-neighbours of the pivot, with the recursive call `f`. -/
def bkLoop (f : List V → List V → List V → List (List V)) (R : List V) :
    List V → List V → List V → List (List V)
  | _, _, [] => []
  | P, X, v :: vs =>
    f (v :: R) (P.filter (compat v)) (X.filter (compat v)) ++
      bkLoop f R (P.filter (fun x => x != v)) (v :: X) vs

/-- Bron–Kerbosch with a pivot and an iteration order, to a depth bound. -/
def bk (pivot : List V → List V → V) (order : List V → List V) :
    Nat → List V → List V → List V → List (List V)
  | 0, _, _, _ => []
  | n + 1, R, P, X =>
    if P.isEmpty && X.isEmpty then [R]
    else bkLoop compat (bk pivot order n) R P X (order (P.filter (fun v => !compat (pivot P X) v)))

/-- The recursion's invariant. -/
structure Inv (U R P X : List V) : Prop where
  clique : Clique compat R
  sub : ∀ a ∈ R, a ∈ U
  cand : ∀ p ∈ P, p ∈ U ∧ ∀ a ∈ R, compat a p = true
  cover : ∀ w ∈ U, w ∉ R → (∀ a ∈ R, compat a w = true) → w ∈ P ∨ w ∈ X

omit [DecidableEq V] in
theorem exists_false_of_all_false {R : List V} {w : V} :
    R.all (fun a => compat a w) = false → ∃ a ∈ R, compat a w = false := by
  induction R with
  | nil => intro h; cases h
  | cons a R ih =>
    intro h
    cases ha : compat a w with
    | false => exact ⟨a, List.mem_cons_self, ha⟩
    | true =>
      have h' : (compat a w && R.all (fun a => compat a w)) = false := h
      rw [ha] at h'
      obtain ⟨b, hb, hb'⟩ := ih h'
      exact ⟨b, List.mem_cons_of_mem _ hb, hb'⟩

omit [DecidableEq V] in
theorem all_true_of_forall {R : List V} {w : V} (h : ∀ a ∈ R, compat a w = true) :
    R.all (fun a => compat a w) = true := by
  induction R with
  | nil => rfl
  | cons a R ih =>
    show (compat a w && R.all (fun a => compat a w)) = true
    rw [h a List.mem_cons_self]
    exact ih (fun b hb => h b (List.mem_cons_of_mem _ hb))

omit [DecidableEq V] in
theorem maximal_of_inv {U R : List V} (h : Inv compat U R [] []) : Maximal compat U R := by
  refine ⟨h.clique, h.sub, ?_⟩
  intro w hw hwR
  cases hall : R.all (fun a => compat a w) with
  | false => exact exists_false_of_all_false compat hall
  | true =>
    have hforall : ∀ a ∈ R, compat a w = true := by
      intro a ha
      exact (List.all_eq_true.mp hall) a ha
    rcases h.cover w hw hwR hforall with hp | hx
    · cases hp
    · cases hx

variable (hsymm : ∀ a b, compat a b = compat b a)
include hsymm

omit [DecidableEq V] in
theorem inv_extend {U R P X : List V} (h : Inv compat U R P X) {v : V} (hvU : v ∈ U)
    (hv : ∀ a ∈ R, compat a v = true) :
    Inv compat U (v :: R) (P.filter (compat v)) (X.filter (compat v)) := by
  refine ⟨?_, ?_, ?_, ?_⟩
  · intro a ha b hb hab
    rcases List.mem_cons.mp ha with ea | ha
    · rcases List.mem_cons.mp hb with eb | hb
      · exact absurd (ea.trans eb.symm) hab
      · rw [ea, hsymm]; exact hv b hb
    · rcases List.mem_cons.mp hb with eb | hb
      · rw [eb]; exact hv a ha
      · exact h.clique a ha b hb hab
  · intro a ha
    rcases List.mem_cons.mp ha with rfl | ha
    · exact hvU
    · exact h.sub a ha
  · intro p hp
    have hp' := List.mem_filter.mp hp
    refine ⟨(h.cand p hp'.1).1, ?_⟩
    intro a ha
    rcases List.mem_cons.mp ha with rfl | ha
    · exact hp'.2
    · exact (h.cand p hp'.1).2 a ha
  · intro w hw hwR hall
    have hwR' : w ∉ R := fun hm => hwR (List.mem_cons_of_mem _ hm)
    have hvw : compat v w = true := hall v List.mem_cons_self
    rcases h.cover w hw hwR' (fun a ha => hall a (List.mem_cons_of_mem _ ha)) with hp | hx
    · exact Or.inl (List.mem_filter.mpr ⟨hp, hvw⟩)
    · exact Or.inr (List.mem_filter.mpr ⟨hx, hvw⟩)

omit hsymm in
theorem inv_skip {U R P X : List V} (h : Inv compat U R P X) (v : V) :
    Inv compat U R (P.filter (fun x => x != v)) (v :: X) := by
  refine ⟨h.clique, h.sub, ?_, ?_⟩
  · intro p hp
    exact h.cand p (List.mem_filter.mp hp).1
  · intro w hw hwR hall
    by_cases hwv : w = v
    · exact Or.inr (hwv ▸ List.mem_cons_self)
    · rcases h.cover w hw hwR hall with hp | hx
      · exact Or.inl (List.mem_filter.mpr ⟨hp, by simp [hwv]⟩)
      · exact Or.inr (List.mem_cons_of_mem _ hx)

theorem bkLoop_maximal (U : List V) (f : List V → List V → List V → List (List V))
    (hf : ∀ R P X, Inv compat U R P X → ∀ C ∈ f R P X, Maximal compat U C) (R : List V) :
    ∀ (vs P X : List V), Inv compat U R P X →
      (∀ v ∈ vs, v ∈ U ∧ ∀ a ∈ R, compat a v = true) →
      ∀ C ∈ bkLoop compat f R P X vs, Maximal compat U C
  | [], _, _, _, _, C, hC => by cases hC
  | v :: vs, P, X, h, hvs, C, hC => by
    rcases List.mem_append.mp hC with hC | hC
    · have hv := hvs v List.mem_cons_self
      exact hf _ _ _ (inv_extend compat hsymm h hv.1 hv.2) C hC
    · exact bkLoop_maximal U f hf R vs _ _ (inv_skip compat h v)
        (fun w hw => hvs w (List.mem_cons_of_mem _ hw)) C hC

/-- Every set the recursion reports from a state satisfying the invariant is maximal. -/
theorem bk_sound (U : List V) (pivot : List V → List V → V) (order : List V → List V)
    (horder : ∀ l, ∀ v ∈ order l, v ∈ l) :
    ∀ (n : Nat) (R P X : List V), Inv compat U R P X → ∀ C ∈ bk compat pivot order n R P X,
      Maximal compat U C
  | 0, _, _, _, _, C, hC => by cases hC
  | n + 1, R, P, X, h, C, hC => by
    unfold bk at hC
    by_cases he : (P.isEmpty && X.isEmpty) = true
    · rw [if_pos he] at hC
      have hC' : C = R := List.mem_singleton.mp hC
      subst hC'
      have hP : P = [] := List.isEmpty_iff.mp (Bool.and_eq_true_iff.mp he).1
      have hX : X = [] := List.isEmpty_iff.mp (Bool.and_eq_true_iff.mp he).2
      subst hP; subst hX
      exact maximal_of_inv compat h
    · rw [if_neg he] at hC
      refine bkLoop_maximal compat hsymm U _ (bk_sound U pivot order horder n) R _ P X h ?_ C hC
      intro v hv
      exact h.cand v (List.mem_filter.mp (horder _ v hv)).1

/-- Every set Bron–Kerbosch reports from the start state (`R = []`, `P = nodes`, `X = []`)
is a maximal compatible set of the nodes. -/
theorem bk_maximal (U : List V) (pivot : List V → List V → V) (order : List V → List V)
    (horder : ∀ l, ∀ v ∈ order l, v ∈ l) (n : Nat) :
    ∀ C ∈ bk compat pivot order n [] U [], Maximal compat U C := by
  refine bk_sound compat hsymm U pivot order horder n [] U [] ⟨?_, ?_, ?_, ?_⟩
  · intro a ha; cases ha
  · intro a ha; cases ha
  · intro p hp; exact ⟨hp, fun a ha => by cases ha⟩
  · intro w hw _ _; exact Or.inl hw

end BronKerbosch

/-! ## Completeness: every maximal compatible set is reported -/

section Completeness
variable {V : Type} [DecidableEq V] (compat : V → V → Bool)

/-- Two lists with the same members. -/
def SameMembers (C M : List V) : Prop :=
  ∀ x, x ∈ C ↔ x ∈ M

/-- Remove the first occurrence of `a`. -/
def removeFirst (a : V) : List V → List V
  | [] => []
  | b :: l => if b = a then l else b :: removeFirst a l

theorem length_removeFirst (a : V) : ∀ l : List V, a ∈ l → (removeFirst a l).length + 1 = l.length
  | [], h => absurd h List.not_mem_nil
  | b :: l, h => by
    unfold removeFirst
    by_cases e : b = a
    · rw [if_pos e]; rfl
    · rw [if_neg e]
      have h' : a ∈ l := by
        rcases List.mem_cons.mp h with h | h
        · exact absurd h.symm e
        · exact h
      simp only [List.length_cons]
      rw [length_removeFirst a l h']

theorem mem_removeFirst {a x : V} (hx : x ≠ a) : ∀ l : List V, x ∈ l → x ∈ removeFirst a l
  | [], h => h
  | b :: l, h => by
    unfold removeFirst
    by_cases e : b = a
    · rw [if_pos e]
      rcases List.mem_cons.mp h with h | h
      · exact absurd (h.trans e) hx
      · exact h
    · rw [if_neg e]
      rcases List.mem_cons.mp h with h | h
      · rw [h]; exact List.mem_cons_self
      · exact List.mem_cons_of_mem _ (mem_removeFirst hx l h)

/-- A duplicate-free list inside another is no longer than it. -/
theorem nodup_length_le_of_subset : ∀ {l₁ l₂ : List V}, l₁.Nodup → (∀ x ∈ l₁, x ∈ l₂) →
    l₁.length ≤ l₂.length
  | [], _, _, _ => Nat.zero_le _
  | a :: t, l₂, h₁, hsub => by
    have h₁' := List.nodup_cons.mp h₁
    have ha : a ∈ l₂ := hsub a List.mem_cons_self
    have htsub : ∀ x ∈ t, x ∈ removeFirst a l₂ := by
      intro x hx
      have hxa : x ≠ a := fun e => h₁'.1 (e ▸ hx)
      exact mem_removeFirst hxa l₂ (hsub x (List.mem_cons_of_mem _ hx))
    have hih := nodup_length_le_of_subset h₁'.2 htsub
    have hlen := length_removeFirst a l₂ ha
    simp only [List.length_cons]
    omega

omit [DecidableEq V] in
theorem length_filter_le_of_imp {p q : V → Bool} (h : ∀ x, q x = true → p x = true) :
    ∀ l : List V, (l.filter q).length ≤ (l.filter p).length
  | [] => Nat.le_refl 0
  | x :: xs => by
    have ih := length_filter_le_of_imp h xs
    rw [List.filter_cons, List.filter_cons]
    cases hq : q x with
    | true =>
      have hp := h x hq
      simp only [hp, ↓reduceIte, List.length_cons]
      exact Nat.succ_le_succ ih
    | false =>
      cases hp : p x with
      | true =>
        simp only [List.length_cons, Bool.false_eq_true, ↓reduceIte]
        exact Nat.le_succ_of_le ih
      | false =>
        simp only [Bool.false_eq_true, ↓reduceIte]
        exact ih

omit [DecidableEq V] in
theorem length_filter_lt_of_imp {p q : V → Bool} (h : ∀ x, q x = true → p x = true) :
    ∀ (l : List V) (y : V), y ∈ l → p y = true → q y = false →
      (l.filter q).length < (l.filter p).length
  | [], _, hy, _, _ => absurd hy List.not_mem_nil
  | x :: xs, y, hy, hpy, hqy => by
    rw [List.filter_cons, List.filter_cons]
    rcases List.mem_cons.mp hy with e | hy
    · subst e
      simp only [hpy, hqy, ↓reduceIte, Bool.false_eq_true, List.length_cons]
      exact Nat.lt_succ_of_le (length_filter_le_of_imp h xs)
    · have ih := length_filter_lt_of_imp h xs y hy hpy hqy
      cases hq : q x with
      | true =>
        have hp := h x hq
        simp only [hp, ↓reduceIte, List.length_cons]
        exact Nat.succ_lt_succ ih
      | false =>
        cases hp : p x with
        | true =>
          simp only [List.length_cons, Bool.false_eq_true, ↓reduceIte]
          exact Nat.lt_succ_of_lt ih
        | false =>
          simp only [Bool.false_eq_true, ↓reduceIte]
          exact ih

/-- The completeness invariant for a maximal set `M`: `R` is part of `M`, the rest of `M`
is still a candidate, no member of `M` is excluded, and every candidate or excluded node
is compatible with all of `R`. -/
structure CInv (U M R P X : List V) : Prop where
  sub : ∀ a ∈ R, a ∈ M
  rest : ∀ m ∈ M, m ∉ R → m ∈ P
  avoid : ∀ x ∈ X, x ∉ M
  candP : ∀ p ∈ P, p ∈ U ∧ ∀ a ∈ R, compat a p = true
  candX : ∀ x ∈ X, x ∈ U ∧ ∀ a ∈ R, compat a x = true

theorem bkLoop_complete (hirr : ∀ a, compat a a = false) {U M : List V}
    (hM : Maximal compat U M) (f : List V → List V → List V → List (List V)) (R : List V)
    (hf : ∀ v P' X', v ∈ M → v ∉ R → CInv compat U M (v :: R) P' X' →
      ∃ C ∈ f (v :: R) P' X', SameMembers C M) :
    ∀ (vs P X : List V), CInv compat U M R P X →
      (∀ v ∈ vs, v ∈ U ∧ ∀ a ∈ R, compat a v = true) → (∃ v ∈ vs, v ∈ M) →
      ∃ C ∈ bkLoop compat f R P X vs, SameMembers C M
  | [], _, _, _, _, hex => by
    obtain ⟨_, hv, _⟩ := hex
    exact absurd hv List.not_mem_nil
  | v :: vs, P, X, h, hvs, hex => by
    have hv := hvs v List.mem_cons_self
    have hvR : v ∉ R := fun hm => by
      have := hv.2 v hm
      rw [hirr] at this
      cases this
    by_cases hvM : v ∈ M
    · have inv : CInv compat U M (v :: R) (P.filter (compat v)) (X.filter (compat v)) := by
        refine ⟨?_, ?_, ?_, ?_, ?_⟩
        · intro a ha
          rcases List.mem_cons.mp ha with e | ha
          · rw [e]; exact hvM
          · exact h.sub a ha
        · intro m hm hmR
          have hmv : m ≠ v := fun e => hmR (by rw [e]; exact List.mem_cons_self)
          have hmR' : m ∉ R := fun hh => hmR (List.mem_cons_of_mem _ hh)
          exact List.mem_filter.mpr ⟨h.rest m hm hmR', hM.1 v hvM m hm (Ne.symm hmv)⟩
        · intro x hx
          exact h.avoid x (List.mem_filter.mp hx).1
        · intro p hp
          have hp' := List.mem_filter.mp hp
          refine ⟨(h.candP p hp'.1).1, fun a ha => ?_⟩
          rcases List.mem_cons.mp ha with e | ha
          · rw [e]; exact hp'.2
          · exact (h.candP p hp'.1).2 a ha
        · intro x hx
          have hx' := List.mem_filter.mp hx
          refine ⟨(h.candX x hx'.1).1, fun a ha => ?_⟩
          rcases List.mem_cons.mp ha with e | ha
          · rw [e]; exact hx'.2
          · exact (h.candX x hx'.1).2 a ha
      obtain ⟨C, hC, hs⟩ := hf v _ _ hvM hvR inv
      exact ⟨C, List.mem_append.mpr (Or.inl hC), hs⟩
    · have hex' : ∃ w ∈ vs, w ∈ M := by
        obtain ⟨w, hw, hwM⟩ := hex
        rcases List.mem_cons.mp hw with e | hw
        · rw [e] at hwM; exact absurd hwM hvM
        · exact ⟨w, hw, hwM⟩
      have inv : CInv compat U M R (P.filter (fun x => x != v)) (v :: X) := by
        refine ⟨h.sub, ?_, ?_, ?_, ?_⟩
        · intro m hm hmR
          have hmv : m ≠ v := fun e => hvM (by rw [← e]; exact hm)
          exact List.mem_filter.mpr ⟨h.rest m hm hmR, bne_iff_ne.mpr hmv⟩
        · intro x hx
          rcases List.mem_cons.mp hx with e | hx
          · rw [e]; exact hvM
          · exact h.avoid x hx
        · intro p hp
          exact h.candP p (List.mem_filter.mp hp).1
        · intro x hx
          rcases List.mem_cons.mp hx with e | hx
          · rw [e]; exact hv
          · exact h.candX x hx
      obtain ⟨C, hC, hs⟩ := bkLoop_complete hirr hM f R hf vs _ _ inv
        (fun w hw => hvs w (List.mem_cons_of_mem _ hw)) hex'
      exact ⟨C, List.mem_append.mpr (Or.inr hC), hs⟩

/-- Completeness: with a pivot drawn from the candidates or the excluded nodes and an
iteration order that visits every node of its list (the code's `sorted`), the recursion
reports every maximal compatible set `M` whose invariant holds, given depth enough to add
the rest of `M`. -/
theorem bk_complete (hsymm : ∀ a b, compat a b = compat b a) (hirr : ∀ a, compat a a = false)
    {U M : List V} (hM : Maximal compat U M) (pivot : List V → List V → V)
    (order : List V → List V)
    (hpivot : ∀ P X : List V, (P.isEmpty && X.isEmpty) = false → pivot P X ∈ P ∨ pivot P X ∈ X)
    (horder : ∀ l, ∀ v ∈ order l, v ∈ l) (hall : ∀ l, ∀ v ∈ l, v ∈ order l) :
    ∀ (n : Nat) (R P X : List V), CInv compat U M R P X →
      (M.filter (fun m => decide (m ∉ R))).length < n →
      ∃ C ∈ bk compat pivot order n R P X, SameMembers C M
  | 0, _, _, _, _, hn => absurd hn (Nat.not_lt_zero _)
  | n + 1, R, P, X, h, hn => by
    unfold bk
    by_cases he : (P.isEmpty && X.isEmpty) = true
    · rw [if_pos he]
      have hP : P = [] := List.isEmpty_iff.mp (Bool.and_eq_true_iff.mp he).1
      refine ⟨R, List.mem_singleton_self R, fun x => ⟨h.sub x, fun hx => ?_⟩⟩
      by_cases hxR : x ∈ R
      · exact hxR
      · have := h.rest x hx hxR
        rw [hP] at this
        exact absurd this List.not_mem_nil
    · rw [if_neg he]
      have he' : (P.isEmpty && X.isEmpty) = false := by
        cases hh : (P.isEmpty && X.isEmpty) with
        | false => rfl
        | true => exact absurd hh he
      have hu := hpivot P X he'
      have hvs : ∀ v ∈ order (P.filter (fun v => !compat (pivot P X) v)),
          v ∈ U ∧ ∀ a ∈ R, compat a v = true :=
        fun v hv => h.candP v (List.mem_filter.mp (horder _ v hv)).1
      have huR : ∀ a ∈ R, compat a (pivot P X) = true := by
        rcases hu with hu | hu
        · exact (h.candP _ hu).2
        · exact (h.candX _ hu).2
      have huU : pivot P X ∈ U := by
        rcases hu with hu | hu
        · exact (h.candP _ hu).1
        · exact (h.candX _ hu).1
      have hex : ∃ v ∈ order (P.filter (fun v => !compat (pivot P X) v)), v ∈ M := by
        cases hany : (order (P.filter (fun v => !compat (pivot P X) v))).any
            (fun v => decide (v ∈ M)) with
        | true =>
          obtain ⟨v, hv, hvM⟩ := List.any_eq_true.mp hany
          exact ⟨v, hv, of_decide_eq_true hvM⟩
        | false =>
          exfalso
          have hno : ∀ v ∈ order (P.filter (fun v => !compat (pivot P X) v)), v ∉ M := by
            intro v hv hvM
            have : (order (P.filter (fun v => !compat (pivot P X) v))).any
                (fun v => decide (v ∈ M)) = true :=
              List.any_eq_true.mpr ⟨v, hv, decide_eq_true hvM⟩
            rw [hany] at this
            cases this
          have hcomp : ∀ a ∈ M, a ∉ R → compat (pivot P X) a = true := by
            intro a ha haR
            cases hc : compat (pivot P X) a with
            | true => rfl
            | false =>
              exfalso
              have ha' : a ∈ P.filter (fun v => !compat (pivot P X) v) :=
                List.mem_filter.mpr ⟨h.rest a ha haR, by rw [hc]; rfl⟩
              exact hno a (hall _ a ha') ha
          have huM : pivot P X ∉ M := by
            intro huM
            have huR' : pivot P X ∉ R := fun hh => by
              have := huR _ hh
              rw [hirr] at this
              cases this
            have := hcomp _ huM huR'
            rw [hirr] at this
            cases this
          obtain ⟨a, haM, hau⟩ := hM.2.2 _ huU huM
          by_cases haR : a ∈ R
          · rw [huR a haR] at hau; cases hau
          · rw [hsymm, hcomp a haM haR] at hau; cases hau
      refine bkLoop_complete compat hirr hM (bk compat pivot order n) R ?_ _ P X h hvs hex
      intro v P' X' hvM hvR inv
      apply bk_complete hsymm hirr hM pivot order hpivot horder hall n (v :: R) P' X' inv
      have hlt : (M.filter (fun m => decide (m ∉ v :: R))).length <
          (M.filter (fun m => decide (m ∉ R))).length := by
        apply length_filter_lt_of_imp _ M v hvM (decide_eq_true hvR)
        · exact decide_eq_false (fun hh => hh List.mem_cons_self)
        · intro x hx
          exact decide_eq_true (fun hh => of_decide_eq_true hx (List.mem_cons_of_mem _ hh))
      exact Nat.lt_of_lt_of_le hlt (Nat.le_of_lt_succ hn)

/-- Every set the recursion reports is free of duplicates, so its length is its size. -/
theorem bkLoop_nodup (hirr : ∀ a, compat a a = false)
    (f : List V → List V → List V → List (List V))
    (hf : ∀ R P X, R.Nodup → (∀ p ∈ P, ∀ a ∈ R, compat a p = true) → ∀ C ∈ f R P X, C.Nodup)
    (R : List V) :
    ∀ (vs P X : List V), R.Nodup → (∀ p ∈ P, ∀ a ∈ R, compat a p = true) →
      (∀ v ∈ vs, ∀ a ∈ R, compat a v = true) → ∀ C ∈ bkLoop compat f R P X vs, C.Nodup
  | [], _, _, _, _, _, C, hC => by cases hC
  | v :: vs, P, X, hR, hP, hvs, C, hC => by
    rcases List.mem_append.mp hC with hC | hC
    · have hvR : v ∉ R := fun hm => by
        have := hvs v List.mem_cons_self v hm
        rw [hirr] at this
        cases this
      refine hf _ _ _ (List.nodup_cons.mpr ⟨hvR, hR⟩) ?_ C hC
      intro p hp a ha
      have hp' := List.mem_filter.mp hp
      rcases List.mem_cons.mp ha with e | ha
      · rw [e]; exact hp'.2
      · exact hP p hp'.1 a ha
    · exact bkLoop_nodup hirr f hf R vs _ _ hR (fun p hp => hP p (List.mem_filter.mp hp).1)
        (fun w hw => hvs w (List.mem_cons_of_mem _ hw)) C hC

theorem bk_nodup (hirr : ∀ a, compat a a = false) (pivot : List V → List V → V)
    (order : List V → List V) (horder : ∀ l, ∀ v ∈ order l, v ∈ l) :
    ∀ (n : Nat) (R P X : List V), R.Nodup → (∀ p ∈ P, ∀ a ∈ R, compat a p = true) →
      ∀ C ∈ bk compat pivot order n R P X, C.Nodup
  | 0, _, _, _, _, _, C, hC => by cases hC
  | n + 1, R, P, X, hR, hP, C, hC => by
    unfold bk at hC
    by_cases he : (P.isEmpty && X.isEmpty) = true
    · rw [if_pos he] at hC
      rw [List.mem_singleton.mp hC]
      exact hR
    · rw [if_neg he] at hC
      exact bkLoop_nodup compat hirr (bk compat pivot order n)
        (bk_nodup hirr pivot order horder n) R _ P X hR hP
        (fun v hv => hP v (List.mem_filter.mp (horder _ v hv)).1) C hC

/-! ### Every compatible set extends to a maximal one -/

/-- Add a node when it is new and compatible with everything kept so far. -/
def growStep (acc : List V) (w : V) : List V :=
  if w ∉ acc ∧ acc.all (fun a => compat a w) = true then acc ++ [w] else acc

/-- Greedily extend `S` by the nodes of `U`, in order. -/
def grow (S U : List V) : List V :=
  U.foldl (growStep compat) S

theorem mem_growStep {acc : List V} {w x : V} (h : x ∈ acc) : x ∈ growStep compat acc w := by
  unfold growStep
  split
  · exact List.mem_append.mpr (Or.inl h)
  · exact h

theorem mem_grow : ∀ (U acc : List V) (x : V), x ∈ acc → x ∈ grow compat acc U
  | [], _, _, h => h
  | w :: ws, acc, x, h => mem_grow ws (growStep compat acc w) x (mem_growStep compat h)

theorem grow_sub (U₀ : List V) : ∀ (U acc : List V), (∀ a ∈ acc, a ∈ U₀) → (∀ w ∈ U, w ∈ U₀) →
    ∀ a ∈ grow compat acc U, a ∈ U₀
  | [], _, h, _ => h
  | w :: ws, acc, h, hU => by
    refine grow_sub U₀ ws (growStep compat acc w) ?_ (fun x hx => hU x (List.mem_cons_of_mem _ hx))
    intro a ha
    unfold growStep at ha
    split at ha
    · rcases List.mem_append.mp ha with ha | ha
      · exact h a ha
      · rw [List.mem_singleton.mp ha]; exact hU w List.mem_cons_self
    · exact h a ha

theorem grow_nodup : ∀ (U acc : List V), acc.Nodup → (grow compat acc U).Nodup
  | [], _, h => h
  | w :: ws, acc, h => by
    refine grow_nodup ws (growStep compat acc w) ?_
    unfold growStep
    split
    · next hc =>
      rw [List.nodup_append]
      refine ⟨h, List.nodup_cons.mpr ⟨List.not_mem_nil, List.nodup_nil⟩, ?_⟩
      intro a ha b hb e
      rw [List.mem_singleton.mp hb] at e
      exact hc.1 (e ▸ ha)
    · exact h

theorem grow_clique (hsymm : ∀ a b, compat a b = compat b a) :
    ∀ (U acc : List V), Clique compat acc → Clique compat (grow compat acc U)
  | [], _, h => h
  | w :: ws, acc, h => by
    refine grow_clique hsymm ws (growStep compat acc w) ?_
    unfold growStep
    split
    · next hc =>
      have hall : ∀ a ∈ acc, compat a w = true := fun a ha => List.all_eq_true.mp hc.2 a ha
      intro a ha b hb hab
      rcases List.mem_append.mp ha with ha | ha <;> rcases List.mem_append.mp hb with hb | hb
      · exact h a ha b hb hab
      · rw [List.mem_singleton.mp hb]; exact hall a ha
      · rw [List.mem_singleton.mp ha, hsymm]; exact hall b hb
      · exact absurd ((List.mem_singleton.mp ha).trans (List.mem_singleton.mp hb).symm) hab
    · exact h

theorem grow_max : ∀ (U acc : List V) (w : V), w ∈ U → w ∉ grow compat acc U →
    ∃ a ∈ grow compat acc U, compat a w = false
  | [], _, _, hw, _ => absurd hw List.not_mem_nil
  | w' :: ws, acc, w, hw, hwn => by
    rcases List.mem_cons.mp hw with e | hw
    · rw [e] at hwn ⊢
      show ∃ a ∈ grow compat (growStep compat acc w') ws, compat a w' = false
      by_cases hc : w' ∉ acc ∧ acc.all (fun a => compat a w') = true
      · have : w' ∈ growStep compat acc w' := by
          unfold growStep
          rw [if_pos hc]
          exact List.mem_append.mpr (Or.inr List.mem_cons_self)
        exact absurd (mem_grow compat ws _ w' this) hwn
      · by_cases hin : w' ∈ acc
        · exact absurd (mem_grow compat ws _ w' (mem_growStep compat hin)) hwn
        · have hfalse : acc.all (fun a => compat a w') = false := by
            cases hh : acc.all (fun a => compat a w') with
            | false => rfl
            | true => exact absurd ⟨hin, hh⟩ hc
          obtain ⟨a, ha, haw⟩ := exists_false_of_all_false compat hfalse
          exact ⟨a, mem_grow compat ws _ a (mem_growStep compat ha), haw⟩
    · exact grow_max ws (growStep compat acc w') w hw hwn

/-- A compatible set drawn from `U` grows to a maximal compatible set of `U` containing it. -/
theorem grow_maximal (hsymm : ∀ a b, compat a b = compat b a) (U S : List V)
    (hS : Clique compat S) (hSU : ∀ a ∈ S, a ∈ U) : Maximal compat U (grow compat S U) :=
  ⟨grow_clique compat hsymm U S hS, grow_sub compat U U S hSU (fun _ h => h),
    fun w hw hwn => grow_max compat U S w hw hwn⟩

end Completeness

/-! ## The relation `families` builds from conflict edges -/

section Conflicts
variable {V : Type} [DecidableEq V]

/-- Two pull requests conflict: an edge joins them, in either direction. -/
def conflicts (edges : List (V × V)) (a b : V) : Bool :=
  edges.contains (a, b) || edges.contains (b, a)

/-- Compatible: distinct and not in conflict (`compatible[n]` in `families`). -/
def conflictCompat (edges : List (V × V)) (a b : V) : Bool :=
  a != b && !conflicts edges a b

theorem conflictCompat_symm (edges : List (V × V)) (a b : V) :
    conflictCompat edges a b = conflictCompat edges b a := by
  unfold conflictCompat conflicts
  rw [bne_comm, Bool.or_comm (edges.contains (a, b))]

/-- The family `choose_families` keeps (any family the enumeration reports) holds no
conflicting pair, and every pull request left out conflicts with a kept one. -/
theorem chosen_family_maximal (edges : List (V × V)) (nodes : List V)
    (pivot : List V → List V → V) (order : List V → List V)
    (horder : ∀ l, ∀ v ∈ order l, v ∈ l) (n : Nat) (C : List V)
    (hC : C ∈ bk (conflictCompat edges) pivot order n [] nodes []) :
    (∀ a ∈ C, a ∈ nodes) ∧ (∀ a ∈ C, ∀ b ∈ C, a ≠ b → conflicts edges a b = false) ∧
      ∀ w ∈ nodes, w ∉ C → ∃ a ∈ C, conflicts edges a w = true := by
  obtain ⟨hcl, hsub, hmax⟩ :=
    bk_maximal (conflictCompat edges) (conflictCompat_symm edges) nodes pivot order horder n C hC
  refine ⟨hsub, ?_, ?_⟩
  · intro a ha b hb hab
    have := hcl a ha b hb hab
    unfold conflictCompat at this
    cases hc : conflicts edges a b
    · rfl
    · rw [hc] at this; simp at this
  · intro w hw hwC
    obtain ⟨a, ha, hf⟩ := hmax w hw hwC
    refine ⟨a, ha, ?_⟩
    have hne : a ≠ w := fun e => hwC (e ▸ ha)
    unfold conflictCompat at hf
    cases hc : conflicts edges a w
    · rw [hc] at hf; simp [hne] at hf
    · rfl

theorem conflictCompat_irrefl (edges : List (V × V)) (a : V) : conflictCompat edges a a = false := by
  unfold conflictCompat
  rw [bne_self_eq_false]
  rfl

/-- The code's pivot: the node of `P ∪ X` with the most compatible candidates (the first
such in list order; the code iterates a set, whose order is arbitrary). -/
def codePivot (compat : V → V → Bool) (d : V) (P X : List V) : V :=
  (P ++ X).foldl
    (fun best u => if (P.filter (compat best)).length < (P.filter (compat u)).length then u else best)
    ((P ++ X).headD d)

omit [DecidableEq V] in
theorem foldl_pick_mem (c : V → V → Bool) :
    ∀ (l : List V) (init : V), l.foldl (fun b u => if c b u = true then u else b) init = init ∨
      l.foldl (fun b u => if c b u = true then u else b) init ∈ l
  | [], _ => Or.inl rfl
  | u :: us, init => by
    simp only [List.foldl_cons]
    by_cases hc : c init u = true
    · rw [if_pos hc]
      rcases foldl_pick_mem c us u with h | h
      · exact Or.inr (by rw [h]; exact List.mem_cons_self)
      · exact Or.inr (List.mem_cons_of_mem _ h)
    · rw [if_neg hc]
      rcases foldl_pick_mem c us init with h | h
      · exact Or.inl h
      · exact Or.inr (List.mem_cons_of_mem _ h)

omit [DecidableEq V] in
/-- The code's pivot is a candidate or an excluded node whenever there is one. -/
theorem codePivot_mem (compat : V → V → Bool) (d : V) (P X : List V)
    (h : (P.isEmpty && X.isEmpty) = false) : codePivot compat d P X ∈ P ∨ codePivot compat d P X ∈ X := by
  have hne : ∃ y, (P ++ X).headD d = y ∧ y ∈ P ++ X := by
    cases P with
    | cons p ps => exact ⟨p, rfl, List.mem_cons_self⟩
    | nil =>
      cases X with
      | cons x xs => exact ⟨x, rfl, List.mem_cons_self⟩
      | nil => cases h
  obtain ⟨y, hy, hym⟩ := hne
  have := foldl_pick_mem
    (fun best u => decide ((P.filter (compat best)).length < (P.filter (compat u)).length))
    (P ++ X) ((P ++ X).headD d)
  have hmem : codePivot compat d P X ∈ P ++ X := by
    unfold codePivot
    simp only [decide_eq_true_eq] at this
    rcases this with e | m
    · rw [e, hy]; exact hym
    · exact m
  exact List.mem_append.mp hmem

/-- The family `choose_families` keeps is a maximum compatible set: it is free of
duplicates, holds no conflicting pair, and no duplicate-free compatible set of the same
candidates is larger. `C` is the first family of the list sorted by size, largest first
(`hbest`); the recursion runs with the code's pivot rule (any pivot drawn from `P ∪ X`)
and its sorted iteration order (any order that visits exactly the nodes of its list),
with depth above the number of candidates (the code's recursion is unbounded). -/
theorem chosen_family_maximum (edges : List (V × V)) (nodes : List V)
    (pivot : List V → List V → V) (order : List V → List V)
    (hpivot : ∀ P X : List V, (P.isEmpty && X.isEmpty) = false → pivot P X ∈ P ∨ pivot P X ∈ X)
    (horder : ∀ l, ∀ v ∈ order l, v ∈ l) (hall : ∀ l, ∀ v ∈ l, v ∈ order l)
    (n : Nat) (hn : nodes.length < n) (C : List V)
    (hC : C ∈ bk (conflictCompat edges) pivot order n [] nodes [])
    (hbest : ∀ C' ∈ bk (conflictCompat edges) pivot order n [] nodes [], C'.length ≤ C.length)
    (S : List V) (hSnd : S.Nodup) (hSsub : ∀ a ∈ S, a ∈ nodes)
    (hScl : ∀ a ∈ S, ∀ b ∈ S, a ≠ b → conflicts edges a b = false) :
    C.Nodup ∧ S.length ≤ C.length := by
  have hsymm := conflictCompat_symm edges
  have hirr := conflictCompat_irrefl edges
  refine ⟨bk_nodup (conflictCompat edges) hirr pivot order horder n [] nodes [] List.nodup_nil
    (fun _ _ _ ha => (by cases ha)) C hC, ?_⟩
  have hS : Clique (conflictCompat edges) S := by
    intro a ha b hb hab
    unfold conflictCompat
    rw [hScl a ha b hb hab, bne_iff_ne.mpr hab]
    rfl
  have hM := grow_maximal (conflictCompat edges) hsymm nodes S hS hSsub
  have hMnd := grow_nodup (conflictCompat edges) nodes S hSnd
  have hMlen : (grow (conflictCompat edges) S nodes).length ≤ nodes.length :=
    nodup_length_le_of_subset hMnd hM.2.1
  have inv : CInv (conflictCompat edges) nodes (grow (conflictCompat edges) S nodes) [] nodes [] :=
    ⟨fun _ ha => (by cases ha), fun m hm _ => hM.2.1 m hm, fun _ hx => (by cases hx),
      fun p hp => ⟨hp, fun _ ha => (by cases ha)⟩, fun _ hx => (by cases hx)⟩
  have hmeasure : ((grow (conflictCompat edges) S nodes).filter
      (fun m => decide (m ∉ ([] : List V)))).length < n :=
    Nat.lt_of_le_of_lt (List.length_filter_le _ _) (Nat.lt_of_le_of_lt hMlen hn)
  obtain ⟨C', hC', hsame⟩ := bk_complete (conflictCompat edges) hsymm hirr hM pivot order hpivot
    horder hall n [] nodes [] inv hmeasure
  have hSC' : ∀ x ∈ S, x ∈ C' := fun x hx => (hsame x).mpr (mem_grow _ nodes S x hx)
  exact Nat.le_trans (nodup_length_le_of_subset hSnd hSC') (hbest C' hC')

/-- Conflicts 1–2 and 2–3 among four pull requests: the enumeration reports exactly the two
maximal families, {1, 3, 4} and {2, 4}. -/
example : bk (conflictCompat [((1 : Nat), (2 : Nat)), (2, 3)]) (fun P X => (P ++ X).headD 0) id 4
    [] [1, 2, 3, 4] [] = [[4, 3, 1], [4, 2]] := by
  decide

/-- The same run with the code's pivot rule reports the same two families. -/
example : bk (conflictCompat [((1 : Nat), (2 : Nat)), (2, 3)])
    (codePivot (conflictCompat [((1 : Nat), (2 : Nat)), (2, 3)]) 0) id 5
    [] [1, 2, 3, 4] [] = [[3, 1, 4], [2, 4]] := by
  decide

end Conflicts

end BraidedTrain
