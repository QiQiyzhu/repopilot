"""Generate hand-designed executable tasks; no task is claimed to be a historical bug."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA = "b17f4c24cf95a02d3197ec493026b6f23c8f2c3e"
tasks = []


def add(
    slug,
    description,
    category,
    path,
    acceptance,
    *,
    old="",
    new="",
    setup=None,
    difficulty="easy",
    assertion="Independent behavioral assertions against the candidate source",
):
    task = {
        "task_id": f"arc-{len(tasks) + 1:03d}-{slug}",
        "description": description,
        "repository": "https://github.com/QiQiyzhu/arc-shift",
        "repository_commit": SHA,
        "origin": "human-designed-contract-exercise",
        "category": category,
        "difficulty": difficulty,
        "acceptance_tests": [
            "node evaluation/acceptance.cjs <workspace> <task-json>",
            "npm run test",
            "npm run typecheck",
        ],
        "required_files": [path],
        "acceptance_js": acceptance,
        "assertion_summary": assertion,
        "setup_patch": setup,
        "reference_patch": {"path": path, "old": old, "new": new},
        "model_results": {
            "status": "not_run",
            "reason": "No paid API invocation is authorized or required for harness validation",
        },
    }
    tasks.append(task)


def bug(slug, description, file, good, bad, acceptance):
    add(
        slug,
        description,
        "Bug Fix",
        file,
        acceptance,
        old=bad,
        new=good,
        setup={"path": file, "old": good, "new": bad},
    )


bug(
    "clamp-upper",
    "Repair clamp so values below, inside and above the interval are bounded correctly.",
    "src/core/math.ts",
    "Math.max(a, Math.min(b, n))",
    "Math.max(a, Math.max(b, n))",
    "const {clamp}=load('src/core/math.ts');assert.equal(clamp(5,0,10),5);assert.equal(clamp(-2,0,10),0);assert.equal(clamp(12,0,10),10);",
)
bug(
    "zero-direction",
    "Prevent NaN direction components for the zero vector.",
    "src/core/math.ts",
    "return n > 0 ?",
    "return n >= 0 ?",
    "const {direction}=load('src/core/math.ts');assert.deepEqual(direction(0,0),{x:0,y:0});",
)
bug(
    "normalize-direction",
    "Normalize diagonal movement to unit length without changing signs.",
    "src/core/math.ts",
    "{ x: x / n, y: y / n }",
    "{ x: x / n, y: y }",
    "const {direction}=load('src/core/math.ts');const a=direction(-3,4);assert.ok(Math.abs(a.x+0.6)<1e-10);assert.ok(Math.abs(a.y-0.8)<1e-10);",
)
bug(
    "rng-upper-inclusive",
    "Restore inclusive integer sampling, including a singleton range.",
    "src/core/math.ts",
    "(b - a + 1)",
    "(b - a)",
    "const {Random}=load('src/core/math.ts');const r=new Random(1);r.next=()=>0.999;assert.equal(r.int(2,5),5);assert.equal(r.int(4,4),4);",
)
bug(
    "shuffle-copy",
    "Shuffling must preserve the caller's input array.",
    "src/core/math.ts",
    "const a = [...xs];",
    "const a = xs as T[];",
    "const {Random}=load('src/core/math.ts');const a=[1,2,3,4,5,6];const before=[...a];const b=new Random(2).shuffle(a);assert.deepEqual(a,before);assert.notEqual(a,b);assert.deepEqual([...b].sort(),before);",
)
bug(
    "critical-boundary",
    "A roll exactly equal to critical chance must remain a normal hit.",
    "src/combat/rules.ts",
    "roll < critChance",
    "roll <= critChance",
    "const {calculateDamage}=load('src/combat/rules.ts');assert.deepEqual(calculateDamage(20,.2,1.8,.2),{damage:20,critical:false});assert.equal(calculateDamage(20,.2,1.8,.199).damage,36);",
)
bug(
    "critical-scaling",
    "Normal hits must not apply the critical multiplier.",
    "src/combat/rules.ts",
    "critical ? critPower : 1",
    "critical ? critPower : critPower",
    "const {calculateDamage}=load('src/combat/rules.ts');assert.equal(calculateDamage(20,0,2,.5).damage,20);assert.equal(calculateDamage(20,1,2,.5).damage,40);",
)
bug(
    "cooldown-zero",
    "Cooldowns must count down and clamp to exactly zero.",
    "src/combat/rules.ts",
    "Math.max(0, remaining - dt)",
    "Math.min(0, remaining - dt)",
    "const {cooldown}=load('src/combat/rules.ts');assert.equal(cooldown(1,.25),.75);assert.equal(cooldown(.1,.5),0);",
)
bug(
    "segment-denominator",
    "Fast diagonal projectiles must hit targets on their swept segment.",
    "src/combat/rules.ts",
    "dx * dx + dy * dy || 1",
    "dx * dx || 1",
    "const {segmentHits}=load('src/combat/rules.ts');assert.equal(segmentHits(0,0,100,100,50,50,1),true);assert.equal(segmentHits(0,0,100,100,50,60,1),false);",
)
bug(
    "segment-endpoint",
    "Swept collision must not hit a target beyond the segment endpoint.",
    "src/combat/rules.ts",
    "Math.min(1, ((x - ax) * dx + (y - ay) * dy)",
    "Math.min(2, ((x - ax) * dx + (y - ay) * dy)",
    "const {segmentHits}=load('src/combat/rules.ts');assert.equal(segmentHits(0,0,10,0,15,0,1),false);assert.equal(segmentHits(0,0,10,0,9.5,0,1),true);",
)
bug(
    "pool-capacity",
    "A pool must allocate its configured capacity, with no hidden extra slot.",
    "src/core/pool.ts",
    "{ length: capacity }",
    "{ length: capacity + 1 }",
    "const {Pool}=load('src/core/pool.ts');const p=new Pool(2,()=>({active:false}));assert.equal(p.items.length,2);assert.ok(p.acquire());assert.ok(p.acquire());assert.equal(p.acquire(),undefined);",
)
bug(
    "pool-misses",
    "Exhaustion must increment the pool's miss counter exactly once per attempt.",
    "src/core/pool.ts",
    "this.misses++;",
    "this.misses += 2;",
    "const {Pool}=load('src/core/pool.ts');const p=new Pool(1,()=>({active:false}));p.acquire();p.acquire();assert.equal(p.misses,1);p.acquire();assert.equal(p.misses,2);",
)
bug(
    "pool-clear",
    "Clearing a pool must release all active slots for reuse.",
    "src/core/pool.ts",
    "item.active = false",
    "item.active = true",
    "const {Pool}=load('src/core/pool.ts');const p=new Pool(2,()=>({active:false}));p.acquire();p.acquire();p.clear();assert.equal(p.count,0);assert.ok(p.acquire());",
)
bug(
    "pool-count",
    "Pool count must report active, rather than inactive, objects.",
    "src/core/pool.ts",
    "if (i.active) n++;",
    "if (!i.active) n++;",
    "const {Pool}=load('src/core/pool.ts');const p=new Pool(3,()=>({active:false}));assert.equal(p.count,0);p.acquire();assert.equal(p.count,1);",
)
bug(
    "wallet-cap",
    "Loading a wallet must clamp negative and excessive resources to valid caps.",
    "src/economy/catalog.ts",
    "Math.max(0, Math.min(LIMITS[key], Math.floor(n)))",
    "Math.max(0, Math.max(LIMITS[key], Math.floor(n)))",
    "const {normalizeWallet}=load('src/economy/catalog.ts');const w=normalizeWallet({coins:-1,keys:200,bombs:2,tonics:90,shards:20});assert.equal(w.coins,0);assert.equal(w.keys,9);assert.equal(w.bombs,2);assert.equal(w.tonics,3);",
)
bug(
    "wallet-floor",
    "Fractional saved resource counts must be floored, not rounded upward.",
    "src/economy/catalog.ts",
    "Math.min(LIMITS[key], Math.floor(n))",
    "Math.min(LIMITS[key], Math.ceil(n))",
    "const {normalizeWallet}=load('src/economy/catalog.ts');assert.equal(normalizeWallet({coins:2.9}).coins,2);assert.equal(normalizeWallet({keys:.8}).keys,0);",
)

test_cases = [
    (
        "distance",
        "src/core/math.ts",
        "distance",
        "assert.equal(distance({x:0,y:0},{x:3,y:4}),5);",
        "Math.hypot(a.x - b.x, a.y - b.y)",
        "Math.abs(a.x - b.x) + Math.abs(a.y - b.y)",
    ),
    (
        "zero-direction",
        "src/core/math.ts",
        "direction",
        "assert.deepEqual(direction(0,0),{x:0,y:0});",
        "return n > 0 ?",
        "return n >= 0 ?",
    ),
    (
        "cooldown",
        "src/combat/rules.ts",
        "cooldown",
        "assert.equal(cooldown(.1,.5),0);assert.equal(cooldown(1,.2),.8);",
        "Math.max(0, remaining - dt)",
        "Math.min(0, remaining - dt)",
    ),
    (
        "weapon-default",
        "src/economy/catalog.ts",
        "weaponId",
        "assert.equal(weaponId('broken'),'arc');assert.equal(weaponId('sword'),'sword');",
        "? value : 'arc'",
        "? value : 'sword'",
    ),
    (
        "wallet-fallback",
        "src/economy/catalog.ts",
        "normalizeWallet",
        "assert.equal(normalizeWallet(null).coins,8);assert.equal(normalizeWallet({coins:NaN}).coins,8);",
        "coins: 8 +",
        "coins: 0 +",
    ),
    (
        "boss-membership",
        "src/progression/catalog.ts",
        "isBoss",
        "assert.equal(isBoss('matron'),true);assert.equal(isBoss('hunter'),false);",
        "BOSSES.includes(kind as BossKind)",
        "kind === 'oracle'",
    ),
]
for slug, module, symbol, body, good, bad in test_cases:
    file = f"tests/repopilot-{slug}.test.ts"
    source = f"import {{ test }} from 'vitest';\nimport assert from 'node:assert/strict';\nimport {{ {symbol} }} from '../{module[:-3]}';\ntest('RepoPilot {slug} behavioral contract', () => {{ {body} }});\n"
    add(
        "test-" + slug,
        f"Add a behavioral regression test for {symbol}. The test must pass the baseline and reject the supplied incorrect behavior; implementation must remain unchanged.",
        "Add Test",
        file,
        f"load('{file}');",
        new=source,
    )
    tasks[-1]["adequacy_mutation"] = {"path": module, "old": good, "new": bad}

features = [
    (
        "lerp",
        "Interpolate two numeric values, preserving both endpoints and allowing extrapolation.",
        "export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;",
        "assert.equal(m.lerp(2,10,0),2);assert.equal(m.lerp(2,10,1),10);assert.equal(m.lerp(2,10,.5),6);assert.equal(m.lerp(2,10,2),18);",
    ),
    (
        "inverseLerp",
        "Add inverseLerp(a,b,value), returning zero for a degenerate interval.",
        "export const inverseLerp = (a: number, b: number, value: number) => a === b ? 0 : (value - a) / (b - a);",
        "assert.equal(m.inverseLerp(2,10,6),.5);assert.equal(m.inverseLerp(4,4,7),0);assert.equal(m.inverseLerp(10,2,6),.5);",
    ),
    (
        "wrapAngle",
        "Add wrapAngle(radians) into [-PI, PI), handling negative turns.",
        "export const wrapAngle = (radians: number) => ((radians + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;",
        "assert.ok(Math.abs(m.wrapAngle(5*Math.PI)+Math.PI)<1e-10);assert.ok(Math.abs(m.wrapAngle(-4*Math.PI))<1e-10);assert.ok(Math.abs(m.wrapAngle(.4)-.4)<1e-10);",
    ),
    (
        "magnitudeSquared",
        "Add magnitudeSquared(x,y) for inexpensive range comparisons.",
        "export const magnitudeSquared = (x: number, y: number) => x * x + y * y;",
        "assert.equal(m.magnitudeSquared(3,4),25);assert.equal(m.magnitudeSquared(-3,4),25);assert.equal(m.magnitudeSquared(0,0),0);",
    ),
    (
        "saturate",
        "Add saturate(value) clamping to [0,1]; reject NaN as zero.",
        "export const saturate = (value: number) => Number.isNaN(value) ? 0 : Math.max(0, Math.min(1, value));",
        "assert.equal(m.saturate(-2),0);assert.equal(m.saturate(.7),.7);assert.equal(m.saturate(8),1);assert.equal(m.saturate(NaN),0);",
    ),
    (
        "mapRange",
        "Add mapRange(value,inLow,inHigh,outLow,outHigh), returning outLow for zero input span.",
        "export const mapRange = (value: number, inLow: number, inHigh: number, outLow: number, outHigh: number) => inHigh === inLow ? outLow : outLow + (value - inLow) / (inHigh - inLow) * (outHigh - outLow);",
        "assert.equal(m.mapRange(5,0,10,20,40),30);assert.equal(m.mapRange(5,2,2,7,9),7);assert.equal(m.mapRange(10,10,0,0,100),0);",
    ),
]
for symbol, description, code, checks in features:
    add(
        "feature-" + symbol.lower(),
        description,
        "Small Feature",
        "src/core/math.ts",
        "const m=load('src/core/math.ts');" + checks,
        old="export const W = 1280,",
        new=code + "\nexport const W = 1280,",
    )

add(
    "refactor-trap-clock",
    "Extract TRAP_PERIOD=4 and TRAP_ACTIVE_AT=2.8 and use both in zoneActive without behavior change.",
    "Refactor",
    "src/rooms/terrain.ts",
    "const m=load('src/rooms/terrain.ts');assert.equal(m.TRAP_PERIOD,4);assert.equal(m.TRAP_ACTIVE_AT,2.8);assert.equal(m.zoneActive({roomTime:2.7}),false);assert.equal(m.zoneActive({roomTime:2.9}),true);assert.equal(m.zoneActive({roomTime:4}),false);assert.ok(read('src/rooms/terrain.ts').includes('w.roomTime % TRAP_PERIOD >= TRAP_ACTIVE_AT'));",
    old="export function zoneActive(w: World) {\n  return w.roomTime % 4 >= 2.8;",
    new="export const TRAP_PERIOD = 4;\nexport const TRAP_ACTIVE_AT = 2.8;\nexport function zoneActive(w: World) {\n  return w.roomTime % TRAP_PERIOD >= TRAP_ACTIVE_AT;",
)
add(
    "refactor-beam-width",
    "Export LASER_HALF_WIDTH and make laserGeometry consume that constant.",
    "Refactor",
    "src/combat/geometry.ts",
    "const m=load('src/combat/geometry.ts');assert.equal(m.LASER_HALF_WIDTH,14);assert.equal(m.laserGeometry({x:0,y:0,aimX:1,aimY:0,state:'telegraph'}).halfWidth,14);assert.ok(read('src/combat/geometry.ts').includes('halfWidth: LASER_HALF_WIDTH'));",
    old="halfWidth: 14,",
    new="halfWidth: LASER_HALF_WIDTH,",
)
tasks[-1]["extra_reference_patch"] = {
    "path": "src/combat/geometry.ts",
    "old": "export function laserGeometry",
    "new": "export const LASER_HALF_WIDTH = 14;\nexport function laserGeometry",
}
add(
    "refactor-starting-coins",
    "Export STARTING_COINS=8 and reference it from startingWallet, retaining preparation bonuses.",
    "Refactor",
    "src/economy/catalog.ts",
    "const m=load('src/economy/catalog.ts');assert.equal(m.STARTING_COINS,8);assert.equal(m.startingWallet({vitality:0,flask:0,stipend:2}).coins,20);assert.ok(read('src/economy/catalog.ts').includes('coins: STARTING_COINS +'));",
    old="coins: 8 +",
    new="coins: STARTING_COINS +",
)
tasks[-1]["extra_reference_patch"] = {
    "path": "src/economy/catalog.ts",
    "old": "export const startingWallet",
    "new": "export const STARTING_COINS = 8;\nexport const startingWallet",
}
add(
    "refactor-base-damage",
    "Export BASE_DAMAGE=16 and have baseStats use it without sharing mutable state.",
    "Refactor",
    "src/combat/rules.ts",
    "const m=load('src/combat/rules.ts');assert.equal(m.BASE_DAMAGE,16);assert.equal(m.baseStats().damage,16);assert.notEqual(m.baseStats(),m.baseStats());assert.ok(read('src/combat/rules.ts').includes('damage: BASE_DAMAGE'));",
    old="damage: 16,",
    new="damage: BASE_DAMAGE,",
)
tasks[-1]["extra_reference_patch"] = {
    "path": "src/combat/rules.ts",
    "old": "export const baseStats",
    "new": "export const BASE_DAMAGE = 16;\nexport const baseStats",
}

add(
    "performance-segment-sqrt",
    "Remove the square-root calculation in segmentHits while preserving strict tangent and nonpositive-radius behavior. Do not claim a speedup without measurement.",
    "Performance",
    "src/combat/rules.ts",
    "const {segmentHits}=load('src/combat/rules.ts');for(let x=-20;x<120;x++)for(const r of [-2,0,1,5]){const near=Math.max(0,Math.min(100,x));assert.equal(segmentHits(0,0,100,0,x,3,r),Math.hypot(near-x,3)<r);}assert.ok(!read('src/combat/rules.ts').includes('return Math.hypot(ax +'));",
    old="return Math.hypot(ax + dx * t - x, ay + dy * t - y) < r;",
    new="const ex = ax + dx * t - x, ey = ay + dy * t - y;\n  return r > 0 && ex * ex + ey * ey < r * r;",
    difficulty="medium",
    assertion="560 boundary comparisons plus removal of the targeted square-root call; no measured latency claim",
)
add(
    "performance-block-sqrt",
    "Replace blocked's distance square root with squared distance while preserving strict tangency and nonpositive radii.",
    "Performance",
    "src/rooms/terrain.ts",
    "const {blocked}=load('src/rooms/terrain.ts');const b=[{x:10,y:10,w:20,h:20}];for(let x=0;x<40;x++)for(const r of [-1,0,1,5]){const dx=x-Math.max(10,Math.min(30,x));assert.equal(blocked(x,15,r,b),Math.abs(dx)<r);}assert.ok(!read('src/rooms/terrain.ts').includes('Math.hypot(x - clamp'));",
    old="(b) =>\n      Math.hypot(x - clamp(x, b.x, b.x + b.w), y - clamp(y, b.y, b.y + b.h)) <\n      radius,",
    new="(b) => {\n      const dx = x - clamp(x, b.x, b.x + b.w);\n      const dy = y - clamp(y, b.y, b.y + b.h);\n      return radius > 0 && dx * dx + dy * dy < radius * radius;\n    },",
    difficulty="medium",
    assertion="160 boundary comparisons plus elimination of the targeted square-root call; no measured latency claim",
)

add(
    "document-wallet-contract",
    "Add docs/contracts/wallet.json documenting all wallet caps and default resources. The document must match executable catalog exports exactly.",
    "Documentation + Code Consistency",
    "docs/contracts/wallet.json",
    "const m=load('src/economy/catalog.ts');const d=JSON.parse(read('docs/contracts/wallet.json'));assert.deepEqual(d.limits,m.LIMITS);assert.deepEqual(d.start,m.startingWallet());",
    new=json.dumps(
        {
            "limits": {"coins": 999, "keys": 9, "bombs": 9, "tonics": 3, "shards": 999},
            "start": {"coins": 8, "keys": 1, "bombs": 2, "tonics": 1, "shards": 0},
        },
        indent=2,
    )
    + "\n",
)
add(
    "document-boss-contract",
    "Add docs/contracts/bosses.json listing the four unlock-gating bosses in catalog order. Verify consistency from actual BOSSES, not prose inference.",
    "Documentation + Code Consistency",
    "docs/contracts/bosses.json",
    "const m=load('src/progression/catalog.ts');const d=JSON.parse(read('docs/contracts/bosses.json'));assert.deepEqual(d.bosses,m.BOSSES);assert.deepEqual(d.relicBosses,m.RELICS.filter(r=>r.boss).map(r=>r.boss));",
    new=json.dumps(
        {
            "bosses": ["warden", "matron", "forgemaster", "oracle"],
            "relicBosses": ["warden", "matron", "forgemaster", "oracle"],
        },
        indent=2,
    )
    + "\n",
)

destination = ROOT / "evaluation/tasks/arc-shift.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(
    json.dumps(
        {"schema_version": 1, "repository_commit": SHA, "count": len(tasks), "tasks": tasks},
        indent=2,
    ),
    encoding="utf-8",
)
print(f"Wrote {len(tasks)} distinct tasks to {destination}")
