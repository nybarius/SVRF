import BraidedTrain.Landing

/-!
# BraidedTrain.Braid — what is gated, what is reused, what commutes

Three results the train relies on, over `Landing`'s `fold`, `Replays` and `landed`. Finite
lists, no Mathlib.

1. The ungated window. `mains` is the list of trees the base branch holds during a
   landing, one per merge. `mem_mains_iff`: a tree is one of them exactly when it is the
   landing of a nonempty prefix; `mains_are_prefix_folds`: each is a prefix fold.
   `AllGated` is the invariant "no ungated tree on the base branch".
   `single_merge_all_gated`: a family landed as one merge commit needs one gate.
   `all_gated_iff_each_prefix`: a family landed one pull request at a time needs a gate
   per landed prefix, exactly. `end_gate_leaves_prefix_ungated`: the gate on the family's
   end tree alone does not cover the first prefix. This is why the train records a
   family stopped midway as PREFIX_LANDED_UNGATED.

2. Retry as one rule. A verdict is a function of what it read: the head and the base
   branch's content over the watched paths (`RetryKey`). `verdict_reuse`: equal keys,
   equal verdict. `retry_iff`: a held head is retried exactly when its key changed, and
   while it has not, its verdict stands (`held_verdict_stands`).
   `no_reopen_outside_reads`: the base moving outside the watched paths changes no
   verdict.

3. Commutation. The union step writes a pull request's paths onto the tree (`apply`);
   writes on disjoint paths commute (`write_comm`, `apply_comm_of_disjoint`), so two
   strands with pairwise disjoint written paths fold to the same tree in either order
   (`strands_comm`). This is what the pairwise conflict read relies on when it keeps
   non-conflicting pull requests in one family. That git's merge of disjoint paths is
   `apply` is the modelling boundary; the landed-tree check remains the hypothesis.
-/

namespace BraidedTrain

variable {Tree Head : Type}

/-- The trees the base branch holds during a landing, one per merge (the start not counted). -/
def mains : Tree → List (Head × Tree) → List Tree
  | _, [] => []
  | _, (_, t') :: rest => t' :: mains t' rest

theorem mains_length : ∀ (base : Tree) (L : List (Head × Tree)), (mains base L).length = L.length
  | _, [] => rfl
  | _, (_, t') :: rest => by
    simp only [mains, List.length_cons]
    rw [mains_length t' rest]

/-- A tree the base branch held is exactly the landing of a nonempty prefix. -/
theorem mem_mains_iff : ∀ (base : Tree) (L : List (Head × Tree)) (t : Tree),
    t ∈ mains base L ↔ ∃ L₁ L₂, L = L₁ ++ L₂ ∧ L₁ ≠ [] ∧ landed base L₁ = t
  | _, [], t => by
    simp only [mains, List.not_mem_nil, false_iff]
    intro h
    obtain ⟨L₁, _, hL, hne, _⟩ := h
    exact hne (List.append_eq_nil_iff.mp hL.symm).1
  | base, (h, t') :: rest, t => by
    constructor
    · intro ht
      rcases List.mem_cons.mp ht with rfl | ht
      · exact ⟨[(h, t)], rest, rfl, List.cons_ne_nil _ _, rfl⟩
      · obtain ⟨L₁, L₂, hL, hne, hl⟩ := (mem_mains_iff t' rest t).mp ht
        refine ⟨(h, t') :: L₁, L₂, ?_, List.cons_ne_nil _ _, ?_⟩
        · rw [hL]; rfl
        · simpa [landed] using hl
    · intro hx
      obtain ⟨L₁, L₂, hL, hne, hl⟩ := hx
      cases L₁ with
      | nil => exact absurd rfl hne
      | cons p L₁' =>
        obtain ⟨h', t''⟩ := p
        simp only [List.cons_append, List.cons.injEq, Prod.mk.injEq] at hL
        obtain ⟨⟨_, ht''⟩, hrest⟩ := hL
        subst ht''
        cases L₁' with
        | nil =>
          simp only [landed] at hl
          subst hl
          exact List.mem_cons_self
        | cons q L₁'' =>
          apply List.mem_cons_of_mem
          exact (mem_mains_iff t' rest t).mpr ⟨q :: L₁'', L₂, hrest, List.cons_ne_nil _ _, by simpa [landed] using hl⟩

theorem mains_are_prefix_folds (step : Tree → Head → Option Tree) {base : Tree}
    {L : List (Head × Tree)} (hr : Replays step base L) (t : Tree) (ht : t ∈ mains base L) :
    ∃ k, fold step base ((L.take k).map Prod.fst) = some t := by
  obtain ⟨L₁, L₂, hL, _, hl⟩ := (mem_mains_iff base L t).mp ht
  refine ⟨L₁.length, ?_⟩
  subst hL
  rw [List.take_left]
  rw [← hl]
  exact fold_of_replays step ((replays_append step).1 hr).1

/-- The invariant: no ungated tree on the base branch during the landing. -/
def AllGated (gate : Tree → Prop) (base : Tree) (L : List (Head × Tree)) : Prop :=
  ∀ t ∈ mains base L, gate t

theorem single_merge_all_gated (gate : Tree → Prop) (base : Tree) (h : Head) (g : Tree) :
    AllGated gate base [(h, g)] ↔ gate g := by
  simp [AllGated, mains]

theorem all_gated_iff_each_prefix (gate : Tree → Prop) (base : Tree) (L : List (Head × Tree)) :
    AllGated gate base L ↔ ∀ L₁ L₂, L = L₁ ++ L₂ → L₁ ≠ [] → gate (landed base L₁) := by
  constructor
  · intro hg L₁ L₂ hL hne
    exact hg _ ((mem_mains_iff base L _).mpr ⟨L₁, L₂, hL, hne, rfl⟩)
  · intro hp t ht
    obtain ⟨L₁, L₂, hL, hne, hl⟩ := (mem_mains_iff base L t).mp ht
    rw [← hl]
    exact hp L₁ L₂ hL hne

theorem end_gate_leaves_prefix_ungated (gate : Tree → Prop) (base : Tree) (h₁ h₂ : Head)
    {t₁ t₂ : Tree} (_hend : gate t₂) (hnot : ¬ gate t₁) :
    ¬ AllGated gate base [(h₁, t₁), (h₂, t₂)] :=
  fun hg => hnot (hg t₁ (by simp [mains]))

/-! ## Retry -/

/-- What a verdict read: the head and the base branch's content over the watched paths. -/
structure RetryKey (Sha Watched : Type) where
  head : Sha
  watched : Watched
  deriving DecidableEq

theorem verdict_reuse {Sha Watched V : Type} (verdict : RetryKey Sha Watched → V)
    {c c' : RetryKey Sha Watched} (h : c = c') : verdict c = verdict c' :=
  congrArg verdict h

/-- A held head is retried exactly when its key changed. -/
def retry {Sha Watched : Type} [DecidableEq Sha] [DecidableEq Watched]
    (held now : RetryKey Sha Watched) : Bool :=
  decide (held ≠ now)

theorem retry_iff {Sha Watched : Type} [DecidableEq Sha] [DecidableEq Watched]
    (held now : RetryKey Sha Watched) : retry held now = true ↔ held ≠ now := by
  simp [retry]

theorem held_verdict_stands {Sha Watched V : Type} [DecidableEq Sha] [DecidableEq Watched]
    (verdict : RetryKey Sha Watched → V) {held now : RetryKey Sha Watched}
    (h : retry held now = false) : verdict held = verdict now := by
  by_cases he : held = now
  · exact congrArg verdict he
  · exact absurd h (by simp [retry, he])

/-- A tree's content over a list of watched paths. -/
def restrict {Path Val : Type} (t : Path → Val) (reads : List Path) : List (Path × Val) :=
  reads.map (fun p => (p, t p))

theorem restrict_congr {Path Val : Type} {t t' : Path → Val} :
    ∀ (reads : List Path), (∀ p ∈ reads, t p = t' p) → restrict t reads = restrict t' reads
  | [], _ => rfl
  | p :: ps, h => by
    simp only [restrict, List.map_cons]
    rw [h p List.mem_cons_self]
    have := restrict_congr ps (fun q hq => h q (List.mem_cons_of_mem _ hq))
    simp only [restrict] at this
    rw [this]

theorem no_reopen_outside_reads {Sha Path Val V : Type}
    (verdict : RetryKey Sha (List (Path × Val)) → V) (sha : Sha) (reads : List Path)
    {t t' : Path → Val} (h : ∀ p ∈ reads, t p = t' p) :
    verdict ⟨sha, restrict t reads⟩ = verdict ⟨sha, restrict t' reads⟩ := by
  rw [restrict_congr reads h]

/-! ## Commutation of disjoint union steps -/

section Commutation
variable {Path Val : Type} [DecidableEq Path]

/-- One written path. -/
def write (t : Path → Val) (p : Path) (v : Val) : Path → Val :=
  fun q => if q = p then v else t q

/-- The union step: a pull request's writes applied in order. -/
def apply : (Path → Val) → List (Path × Val) → Path → Val
  | t, [] => t
  | t, (p, v) :: ws => apply (write t p v) ws

theorem write_eq_of_ne (t : Path → Val) {p q : Path} (v : Val) (h : q ≠ p) :
    write t p v q = t q := by
  simp [write, h]

/-- A path no write touches keeps its value. -/
theorem apply_eq_of_not_written (t : Path → Val) :
    ∀ (a : List (Path × Val)) (p : Path), (∀ x ∈ a, x.1 ≠ p) → apply t a p = t p
  | [], _, _ => rfl
  | (q, v) :: ws, p, h => by
    simp only [apply]
    rw [apply_eq_of_not_written (write t q v) ws p (fun x hx => h x (List.mem_cons_of_mem _ hx))]
    exact write_eq_of_ne t v (Ne.symm (h (q, v) List.mem_cons_self))

/-- Two pull requests whose written paths never meet. -/
def DisjointWrites (a b : List (Path × Val)) : Prop :=
  ∀ x ∈ a, ∀ y ∈ b, x.1 ≠ y.1

theorem write_comm (t : Path → Val) {p q : Path} (hpq : p ≠ q) (v w : Val) :
    write (write t p v) q w = write (write t q w) p v := by
  funext r
  simp only [write]
  by_cases hq : r = q
  · by_cases hp : r = p
    · exact absurd (hp.symm.trans hq) hpq
    · simp [hq, Ne.symm hpq]
  · by_cases hp : r = p
    · simp [hp, hpq]
    · simp [hq, hp]

theorem apply_write_comm : ∀ (t : Path → Val) (b : List (Path × Val)) (p : Path) (v : Val),
    (∀ y ∈ b, p ≠ y.1) → apply (write t p v) b = write (apply t b) p v
  | _, [], _, _, _ => rfl
  | t, (q, w) :: ws, p, v, h => by
    simp only [apply]
    rw [write_comm t (h (q, w) List.mem_cons_self) v w]
    exact apply_write_comm (write t q w) ws p v (fun y hy => h y (List.mem_cons_of_mem _ hy))

theorem apply_comm_of_disjoint (t : Path → Val) : ∀ {a b : List (Path × Val)},
    DisjointWrites a b → apply (apply t a) b = apply (apply t b) a := by
  intro a
  induction a generalizing t with
  | nil => intro b _; rfl
  | cons x as ih =>
    intro b hd
    obtain ⟨p, v⟩ := x
    simp only [apply]
    rw [ih (write t p v) (fun y hy z hz => hd y (List.mem_cons_of_mem _ hy) z hz)]
    rw [apply_write_comm t b p v (fun y hy => hd (p, v) List.mem_cons_self y hy)]

theorem apply_append (t : Path → Val) : ∀ (a b : List (Path × Val)),
    apply t (a ++ b) = apply (apply t a) b
  | [], _ => rfl
  | (p, v) :: as, b => by
    simp only [List.cons_append, apply]
    exact apply_append (write t p v) as b

/-- The union step as the train's step: never a conflict on disjoint paths. -/
def unionStep (t : Path → Val) (h : List (Path × Val)) : Option (Path → Val) :=
  some (apply t h)

theorem fold_union : ∀ (t : Path → Val) (hs : List (List (Path × Val))),
    fold unionStep t hs = some (hs.foldl apply t)
  | _, [] => rfl
  | t, h :: hs => by
    simp only [fold, unionStep, List.foldl_cons]
    exact fold_union (apply t h) hs

theorem foldl_apply_disjoint (t : Path → Val) (a : List (Path × Val)) :
    ∀ (s : List (List (Path × Val))), (∀ b ∈ s, DisjointWrites a b) →
      s.foldl apply (apply t a) = apply (s.foldl apply t) a
  | [], _ => rfl
  | b :: bs, h => by
    simp only [List.foldl_cons]
    rw [apply_comm_of_disjoint t (h b List.mem_cons_self)]
    exact foldl_apply_disjoint (apply t b) a bs (fun c hc => h c (List.mem_cons_of_mem _ hc))

theorem foldl_strands_comm (t : Path → Val) :
    ∀ (s₁ s₂ : List (List (Path × Val))), (∀ a ∈ s₁, ∀ b ∈ s₂, DisjointWrites a b) →
      s₂.foldl apply (s₁.foldl apply t) = s₁.foldl apply (s₂.foldl apply t)
  | [], _, _ => rfl
  | a :: as, s₂, h => by
    simp only [List.foldl_cons]
    rw [foldl_strands_comm (apply t a) as s₂ (fun a' ha' b hb => h a' (List.mem_cons_of_mem _ ha') b hb)]
    rw [foldl_apply_disjoint t a s₂ (fun b hb => h a List.mem_cons_self b hb)]

/-- Two strands with disjoint written paths fold to the same tree in either order. -/
theorem strands_comm (t : Path → Val) {s₁ s₂ : List (List (Path × Val))}
    (hd : ∀ a ∈ s₁, ∀ b ∈ s₂, DisjointWrites a b) :
    fold unionStep t (s₁ ++ s₂) = fold unionStep t (s₂ ++ s₁) := by
  rw [fold_union, fold_union, List.foldl_append, List.foldl_append]
  rw [foldl_strands_comm t s₁ s₂ hd]

end Commutation

end BraidedTrain
