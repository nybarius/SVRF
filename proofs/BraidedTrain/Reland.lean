import BraidedTrain.Braid

/-!
# BraidedTrain.Reland — an ordered re-land lands the same tree

A pull request whose commits are out of order (code before its tests, or tests and code
in one commit) is not held for a person: the train re-lands its content on a clean branch
as a tests commit, a code commit and a docs commit, with the same final tree.

A history is a list of commits, each a list of writes; `tree base h` is the tree it lands
(`apply` folded). `finalWrites` reads, for every path the history wrote, the value it
holds in the landed tree; `reland` partitions those by `kind` into the three commits.
`reland_tree`: the re-land lands exactly the tree the history landed, for any kind
function. `reland_restrict` and `reland_gate`: so any gate reading the tree gives the
same verdict. What the re-land changes is the order alone: `mem_testsOf`, `mem_codeOf`,
`mem_docsOf` say which paths each of the three commits carries. The head sha changes too,
so a verdict keyed on the sha is read again, and a verdict keyed on the tree stands
(`verdict_reuse`).
-/

namespace BraidedTrain

/-- The three kinds of path the history-order check distinguishes. -/
inductive Kind
  | test
  | code
  | doc
  deriving DecidableEq

section
variable {Path Val : Type} [DecidableEq Path]

/-- Every path a history writes. -/
def written : List (List (Path × Val)) → List Path
  | [] => []
  | c :: cs => c.map Prod.fst ++ written cs

/-- The tree a history lands from a base: its commits' writes folded in order. -/
def tree (base : Path → Val) (h : List (List (Path × Val))) : Path → Val :=
  h.foldl apply base

omit [DecidableEq Path] in
theorem mem_written_cons {c : List (Path × Val)} {cs : List (List (Path × Val))} {p : Path} :
    p ∈ written (c :: cs) ↔ (∃ x ∈ c, x.1 = p) ∨ p ∈ written cs := by
  simp only [written, List.mem_append, List.mem_map]

theorem tree_not_written (base : Path → Val) :
    ∀ (h : List (List (Path × Val))) (p : Path), p ∉ written h → tree base h p = base p
  | [], _, _ => rfl
  | c :: cs, p, hp => by
    have hc : ∀ x ∈ c, x.1 ≠ p := fun x hx hxp => hp (mem_written_cons.mpr (Or.inl ⟨x, hx, hxp⟩))
    have hcs : p ∉ written cs := fun h' => hp (mem_written_cons.mpr (Or.inr h'))
    show tree (apply base c) cs p = base p
    rw [tree_not_written (apply base c) cs p hcs]
    exact apply_eq_of_not_written base c p hc

/-- A write list whose every entry agrees with `T` writes `T`'s value at every path it writes. -/
theorem apply_written (T : Path → Val) :
    ∀ (t : Path → Val) (a : List (Path × Val)), (∀ x ∈ a, x.2 = T x.1) →
      ∀ p, p ∈ a.map Prod.fst → apply t a p = T p
  | _, [], _, _, hp => absurd hp (by simp)
  | t, (q, v) :: ws, ha, p, hp => by
    simp only [apply]
    by_cases hw : p ∈ ws.map Prod.fst
    · exact apply_written T (write t q v) ws (fun x hx => ha x (List.mem_cons_of_mem _ hx)) p hw
    · have hpq : p = q := by
        simp only [List.map_cons, List.mem_cons] at hp
        exact hp.resolve_right hw
      rw [apply_eq_of_not_written (write t q v) ws p
            (fun x hx hxp => hw (List.mem_map.mpr ⟨x, hx, hxp⟩))]
      subst hpq
      simp only [write, if_true]
      exact ha (p, v) List.mem_cons_self

/-- A history whose every entry agrees with `T` lands `T`'s value at every path it writes. -/
theorem tree_agrees (T : Path → Val) :
    ∀ (t : Path → Val) (cs : List (List (Path × Val))), (∀ c ∈ cs, ∀ x ∈ c, x.2 = T x.1) →
      ∀ p, p ∈ written cs → tree t cs p = T p
  | _, [], _, _, hp => absurd hp (by simp [written])
  | t, c :: cs, hcs, p, hp => by
    show tree (apply t c) cs p = T p
    by_cases hw : p ∈ written cs
    · exact tree_agrees T (apply t c) cs (fun c' hc' => hcs c' (List.mem_cons_of_mem _ hc')) p hw
    · have hc : p ∈ c.map Prod.fst := by
        rcases mem_written_cons.mp hp with ⟨x, hx, hxp⟩ | h'
        · exact List.mem_map.mpr ⟨x, hx, hxp⟩
        · exact absurd h' hw
      rw [tree_not_written (apply t c) cs p hw]
      exact apply_written T t c (hcs c List.mem_cons_self) p hc

/-- For every path the history wrote, the value it holds in the landed tree. -/
def finalWrites (base : Path → Val) (h : List (List (Path × Val))) : List (Path × Val) :=
  (written h).map (fun p => (p, tree base h p))

def testsOf (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind) :
    List (Path × Val) :=
  (finalWrites base h).filter (fun x => decide (kind x.1 = Kind.test))

def codeOf (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind) :
    List (Path × Val) :=
  (finalWrites base h).filter (fun x => decide (kind x.1 = Kind.code))

def docsOf (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind) :
    List (Path × Val) :=
  (finalWrites base h).filter (fun x => decide (kind x.1 = Kind.doc))

/-- The ordered re-land: the tests commit, the code commit, the docs commit. -/
def reland (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind) :
    List (List (Path × Val)) :=
  [testsOf base h kind, codeOf base h kind, docsOf base h kind]

theorem mem_testsOf (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind)
    {x : Path × Val} (hx : x ∈ testsOf base h kind) : kind x.1 = Kind.test :=
  of_decide_eq_true (List.mem_filter.mp hx).2

theorem mem_codeOf (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind)
    {x : Path × Val} (hx : x ∈ codeOf base h kind) : kind x.1 = Kind.code :=
  of_decide_eq_true (List.mem_filter.mp hx).2

theorem mem_docsOf (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind)
    {x : Path × Val} (hx : x ∈ docsOf base h kind) : kind x.1 = Kind.doc :=
  of_decide_eq_true (List.mem_filter.mp hx).2

theorem mem_reland_final (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind)
    {c : List (Path × Val)} (hc : c ∈ reland base h kind) {x : Path × Val} (hx : x ∈ c) :
    x ∈ finalWrites base h := by
  simp only [reland, List.mem_cons, List.not_mem_nil, or_false] at hc
  rcases hc with rfl | rfl | rfl <;> exact (List.mem_filter.mp hx).1

theorem mem_finalWrites (base : Path → Val) (h : List (List (Path × Val))) {x : Path × Val}
    (hx : x ∈ finalWrites base h) : x.1 ∈ written h ∧ x.2 = tree base h x.1 := by
  obtain ⟨q, hq, rfl⟩ := List.mem_map.mp hx
  exact ⟨hq, rfl⟩

theorem written_reland (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind)
    (p : Path) : p ∈ written (reland base h kind) ↔ p ∈ written h := by
  constructor
  · intro hp
    simp only [reland, written, List.append_nil, List.mem_append, List.mem_map] at hp
    rcases hp with ⟨x, hx, rfl⟩ | ⟨x, hx, rfl⟩ | ⟨x, hx, rfl⟩ <;>
      exact (mem_finalWrites base h (List.mem_filter.mp hx).1).1
  · intro hp
    have hmem : (p, tree base h p) ∈ finalWrites base h := List.mem_map.mpr ⟨p, hp, rfl⟩
    simp only [reland, written, List.append_nil, List.mem_append, List.mem_map]
    cases hk : kind p
    · exact Or.inl ⟨(p, tree base h p), List.mem_filter.mpr ⟨hmem, by simp [hk]⟩, rfl⟩
    · exact Or.inr (Or.inl ⟨(p, tree base h p), List.mem_filter.mpr ⟨hmem, by simp [hk]⟩, rfl⟩)
    · exact Or.inr (Or.inr ⟨(p, tree base h p), List.mem_filter.mpr ⟨hmem, by simp [hk]⟩, rfl⟩)

/-- The ordered re-land lands exactly the tree the history landed. -/
theorem reland_tree (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind) :
    tree base (reland base h kind) = tree base h := by
  funext p
  by_cases hp : p ∈ written h
  · exact tree_agrees (tree base h) base (reland base h kind)
      (fun c hc x hx => (mem_finalWrites base h (mem_reland_final base h kind hc hx)).2)
      p ((written_reland base h kind p).mpr hp)
  · rw [tree_not_written base _ p (fun hw => hp ((written_reland base h kind p).mp hw)),
        tree_not_written base h p hp]

/-- The re-landed tree has the same content over any list of paths. -/
theorem reland_restrict (reads : List Path) (base : Path → Val) (h : List (List (Path × Val)))
    (kind : Path → Kind) :
    restrict (tree base (reland base h kind)) reads = restrict (tree base h) reads := by
  rw [reland_tree]

/-- Every gate reading the tree over some paths gives the same verdict after the re-land. -/
theorem reland_gate {V : Type} (gate : List (Path × Val) → V) (reads : List Path)
    (base : Path → Val) (h : List (List (Path × Val))) (kind : Path → Kind) :
    gate (restrict (tree base (reland base h kind)) reads) = gate (restrict (tree base h) reads) := by
  rw [reland_tree]

end

end BraidedTrain
