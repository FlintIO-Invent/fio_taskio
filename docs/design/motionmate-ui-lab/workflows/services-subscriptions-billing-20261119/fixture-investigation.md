# Portal fixture investigation

The original portal class fails all ten tests during setup on both AFTER and
frozen BEFORE: its second BusinessUser is created before any subscription exists.
The current quota guard correctly refuses this unsupported capacity state.
Raw logs: `after/backend.log`, `after/baseline-portal-fixture.log`. No application
source, financial calculation, quota rule or provider code changed.

The new approved test file inherits the portal tests with a valid bootstrap: an
active local synthetic subscription permits the two fixture memberships, then
only that setup row is removed before the inherited tests construct their
original provider states. Nine cases inherit their bodies without change. The
tenth negative-state case keeps all original cases/assertions and creates its
owner while the synthetic workspace is active, then marks it inactive before
evaluation; creating membership in an already inactive workspace is also
correctly refused by the guard. Intermediate raw results remain retained.

A supplemental keyboard check measured contrast during an in-progress theme
transition. Those findings are retained externally; steady-theme checks use
reduced motion and wait for the theme to settle. This does not alter the frozen
Catalogue or Data Import implementation.

All 142 Django cases passed after the fixture corrections. Native harness fixes
retain migration-seeded plans between its four TransactionTestCase journeys,
wait for keyboard-submitted navigation, and use loopback Route.fetch with
max_redirects=0 to capture actual Django POST/CSRF/302 responses before stopping
provider navigation. Provider SDK responses are mocked and browser external DNS
is also disabled. Three provider journeys passed before the final keyboard wait
fix; the final four-journey run records the complete current result.

Visual inspection found a narrow Seats label wrapping mid-word. A scoped CSS
flex constraint fixes the label/value allocation; it changes no data or forms.
This is validation refinement within the approved CSS path, not another design
or implementation phase. Source BEFORE stays frozen; AFTER alone was refreshed.
