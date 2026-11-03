---
title: Testing strategy and the test pyramid
minutes: 40
objectives:
  - Apply the test pyramid and recognise the cost of flaky and slow tests
  - Write unit tests and contract tests that give fast reliable feedback
  - Add load, resilience and exploratory testing without slowing every commit
---
Tests are the safety net that lets you change code quickly. The goal is a suite that is fast, trustworthy and covers risk, not a suite that is big.

@concept The test pyramid
@plain
Have many fast, small tests at the bottom, fewer integration tests in the middle and very few slow end-to-end tests at the top.
@problem
A suite made mostly of browser tests is slow, flaky and hard to debug, so developers stop trusting or running it.
@does
- **Unit tests**: milliseconds, no network or database; run on every save and commit.
- **Integration tests**: components with real databases or queues (often in containers); seconds to minutes.
- **End-to-end tests**: a few critical user journeys in a deployed environment.
- Costs rise and feedback slows as you go up; aim for most coverage at the lowest level that can prove the behaviour.
@diagram layers
caption: The test pyramid from top to bottom
layers:
  - {label: "Few", nodes: ["End to end|critical journeys|bad"]}
  - {label: "Some", nodes: ["Integration and contract|real dependencies|warn"]}
  - {label: "Many", nodes: ["Unit|fast and isolated|ok"]}
@h Running by level
```bash title="Separate fast and slow suites" lab
echo "pytest -q -m 'not integration'      # unit tests on every commit"
echo "pytest -q -m integration            # run in CI with containers"
echo "playwright test --grep @smoke       # a handful of end-to-end checks after deploy"
```
@check
Why not test everything end to end? || It is slow, flaky and gives vague failures, so it is used only for critical journeys.
@end

@concept Unit tests that last
@plain
A good unit test checks behaviour through the public interface, runs fast, is independent of other tests and fails for one clear reason.
@problem
Tests tied to implementation details break on every refactor, so people avoid refactoring. Tests that share state fail randomly.
@does
- Structure: arrange, act, assert. One concept per test, with descriptive names.
- Use test doubles (stubs, fakes) for slow or external dependencies; prefer fakes over heavy mocking.
- Parametrised tests cover many inputs compactly. Property-based testing explores random inputs.
- Run in any order and in parallel.
@diagram flow
caption: Structure of a test
numbered: true
nodes:
  - "Arrange|set up inputs|info"
  - "Act|call the code|app"
  - "Assert|check the result|ok"
@h Example with pytest
```python title="test_pricing.py" lab
import pytest

def price_with_tax(net, rate):
    if net < 0:
        raise ValueError("net must not be negative")
    return round(net * (1 + rate), 2)

@pytest.mark.parametrize("net,rate,expected", [(100, 0.18, 118.0), (19.99, 0.05, 20.99), (0, 0.18, 0.0)])
def test_price_with_tax(net, rate, expected):
    assert price_with_tax(net, rate) == expected

def test_negative_rejected():
    with pytest.raises(ValueError):
        price_with_tax(-1, 0.18)
```
@check
What makes a unit test brittle? || Coupling to implementation details such as private methods or call order instead of observable behaviour.
@end

@concept Integration tests and test containers
@plain
Integration tests check that your code works with real neighbours: a database, message queue or another service, not just mocks of them.
@problem
Mocks can agree with your assumptions while the real system disagrees: SQL dialects, serialisation, constraints and timeouts only show against the real thing.
@does
- Start real dependencies in containers (Testcontainers, Docker Compose, services in CI).
- Use a fresh database per run, apply real migrations, and clean data between tests.
- Keep them deterministic: fixed clocks and seeded random values.
- Run on pull requests; they take longer than unit tests but must stay under a few minutes.
@diagram flow
caption: Integration test with a real database
numbered: true
nodes:
  - "Start Postgres|container|env"
  - "Run migrations|real schema|app"
  - "Run tests|against the DB|warn"
  - "Tear down|clean state|ok"
@h CI service container
```yaml title="GitHub Actions service container" nocheck
jobs:
  integration:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: {POSTGRES_PASSWORD: test}
        ports: ["5432:5432"]
        options: --health-cmd "pg_isready -U postgres" --health-interval 5s --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - run: make migrate test-integration
        env: {DATABASE_URL: "postgres://postgres:test@localhost:5432/postgres"}
```
@check
Why use a real database in integration tests? || Dialects, constraints and migrations behave differently from mocks and fail only against the real engine.
@end

@concept Contract testing for services
@plain
A contract test checks that a consumer and a provider agree on the shape of an API without running both together in a full environment.
@problem
In microservices, one team changes a response field and breaks another team in production. Full end-to-end environments to catch this are slow and flaky.
@does
- Consumers publish the requests and responses they rely on (contracts); providers verify they still satisfy every contract in their CI.
- Tools: Pact for consumer-driven contracts; OpenAPI diff tools for schema compatibility.
- Detects breaking changes (removed field, changed type) before merge.
- Complements, not replaces, integration tests.
@diagram seq
caption: Consumer-driven contract
actors: ["Consumer|checkout service|app", "Broker|stores contracts|cp", "Provider|orders service|env"]
steps:
  - "0>1: publish contract | req"
  - "2>1: fetch contracts | req"
  - "1>2: contracts | resp"
  - "note 2..2: replay requests, compare responses"
  - "2>1: verification result | resp"
@h Schema compatibility check
```bash title="Detect a breaking OpenAPI change" lab
echo "oasdiff breaking openapi-main.yaml openapi-branch.yaml   # fails on removed fields or changed types"
echo "wire it into the pull request pipeline"
```
@check
Who verifies a contract, the consumer or the provider? || The provider verifies in its own pipeline that it still meets what consumers published.
@end

@concept Flaky tests and test speed
@plain
A flaky test sometimes passes and sometimes fails with no code change. Slow suites cause people to skip tests. Both erode trust.
@problem
If a failing pipeline is usually "just flaky", real failures get ignored, and engineers re-run until green.
@does
- Causes: shared state, time and ordering assumptions, network calls, race conditions, test data leakage.
- Quarantine a flaky test immediately, track it, and fix or delete it within days.
- Speed: run in parallel, cache dependencies, split slow suites, run only affected tests on a PR and everything nightly.
- Measure: flake rate, duration percentiles and queue time.
@diagram flow
caption: Handling a flaky test
numbered: true
nodes:
  - "Detect|fails then passes on retry|warn"
  - "Quarantine|do not block merges|info"
  - "Fix root cause|isolate state|app"
  - "Restore|back to the gate|ok"
@h Find flakes by repetition
```bash title="Repeat a test to expose flakiness" lab
for i in $(seq 1 20); do pytest -q tests/test_orders.py -p no:randomly >/dev/null 2>&1 || echo "run $i failed"; done 2>/dev/null | head
echo "or: pytest --count=50 -x tests/test_orders.py   # with pytest-repeat"
```
@check
Why should a flaky test be quarantined quickly? || Otherwise the team learns to ignore red builds, and real failures slip through.
@end

@concept Load, performance and resilience testing
@plain
These tests check how the system behaves under stress: many users, large data, and failures of dependencies.
@problem
Functional tests pass, and then the system collapses on a sale day or when a database fails over.
@does
- **Load**: expected peak traffic; **stress**: beyond limits to find the breaking point; **soak**: hours at normal load to expose leaks.
- Tools: k6, Locust, Gatling, JMeter; run against staging with production-like sizing.
- Set pass criteria from SLOs, such as p95 latency under 400 ms and error rate under 0.1 percent.
- **Resilience / chaos**: kill pods, add latency, drain nodes (Chaos Mesh, Litmus, AWS Fault Injection Service).
@diagram cmp
caption: Kinds of non-functional tests
cards:
  - {h: "Load", kind: app, items: ["Expected peak", "Checks SLO under load"]}
  - {h: "Stress", kind: warn, items: ["Beyond capacity", "Finds the breaking point"]}
  - {h: "Soak", kind: info, items: ["Hours or days", "Finds leaks and drift"]}
  - {h: "Chaos", kind: bad, items: ["Inject failures", "Checks recovery"]}
@h k6 script with thresholds
```javascript title="loadtest.js" nocheck
import http from 'k6/http';
import { check } from 'k6';
export const options = {
  vus: 50, duration: '2m',
  thresholds: { http_req_duration: ['p(95)<400'], http_req_failed: ['rate<0.001'] },
};
export default function () {
  const r = http.get('https://staging.example.com/api/products');
  check(r, { 'status is 200': (x) => x.status === 200 });
}
```
@check
Where do pass criteria for a load test come from? || From your SLOs, for example latency percentiles and error rate.
@end

@concept Exploratory testing and quality ownership
@plain
Automated checks confirm known expectations. People exploring the product find the surprises scripts do not look for.
@problem
Fully scripted testing misses usability issues and odd combinations. Leaving quality to a separate QA team at the end recreates the wall.
@does
- Time-boxed sessions with a charter ("explore refund flow with edge-case inputs") and notes on findings.
- The whole team owns quality; testers coach, design strategy and explore.
- Bug bashes before major releases and dogfooding (using your own product) add coverage.
- Production is also a test environment: monitoring and canaries find what staging cannot.
@diagram flow
caption: Exploratory session
numbered: true
nodes:
  - "Charter|goal and time box|info"
  - "Explore|try, observe, vary|app"
  - "Note findings|bugs, questions|warn"
  - "Automate the valuable ones|regression tests|ok"
@h Charter template
```text title="Session charter"
Explore    the refund flow
With       expired cards, partial refunds and double clicks
To discover duplicate refunds or confusing messages
Time box   60 minutes
```
@check
What happens to a bug found by exploration? || It is fixed, and a regression test is added so it cannot return unnoticed.
@end
