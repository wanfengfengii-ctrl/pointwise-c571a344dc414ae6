# 迟到夹位备注的交班约定

白班记录备注时看到的是当时的夹位。排程变更可以把夹位随整段移走，也可以拆掉原位。夜班在关掉白班库后接收备注，按实际观察和终版处理。V1 的收料、搬段、冻结、装夹方式、单版件和原账入口见 README.md。

## 观察和搬动

继续用 `layout.freeze.freeze` 冻结排程。此后每次成功冻结都须固定该草稿当时的实际编辑截面。沿用 V1 的零基半开区间和搬前切口坐标。目的地为段的任一端点时沿用 V1 原样无操作的行为。两次合法冻结可以对应同一编辑截面。旧库中缺少这种绑定的修订继续可按 V1 发行和领取。

夹位是有方向的缝。相邻两片用左片号、右片号表示。首缝的左侧、尾缝的右侧用 `None` 表示，在 JSON 中是 `null`。空排程仅有 `(None, None)` 一个夹位。一次有效搬动保留段内夹位，拆除原顺序中的搬段起止切口及插入切口，其余夹位继续存续。新出现的夹位与曾经拆除的同名夹位属于不同次出现。冻结之间发生的每次有效搬动都计入，包括未单独冻结的中途变序。

## 发行和接纳

`exchange.issue.issue_layout(db, batch_id, start_revision, end_revision) -> bytes` 按同一批、同一草稿的两个已绑定截面的冻结修订发行。起止按冻结先后，允许同一修订。备注可引用含起止在内的任一已绑定截面的冻结修订。载荷须让隔离端核对这些观察、区间内实际有效搬动对夹位的影响及终版的一致性。晚于终版的移动、冻结或同名夹具改档不影响指定起止件。同一对端点再发行字节相同。查询不存在的修订报 `KeyError`，批次不符、端点倒序、端点缺截面绑定或证据矛盾报 `ValueError`。

件是 UTF-8 JSON，沿用 V1 的 `version`、`directory` 和 `payload` 外壳，版本值为整数 `2`。V2 的 `payload` 有 `start_revision`、`end_revision`、`terminal` 和 `evidence` 四个字段。`terminal` 是用终版事实构成的原 V1 载荷对象，含 `batch_id`、`revision_id`、`intake_receipt_id`、`source`、`specimens`、`order` 和 `profile`。目录沿用原三字段，以终版批次、终版修订和完整 V2 规范载荷的 SHA-256 为准。规范载荷使用 V1 的排序键、紧凑分隔符及 JSON ASCII 转义。`evidence` 的表示由实现选择，可全量扫描或重放。必须校验格式、目录、终版可装夹性和件内证据的一致性。即使摘要吻合，互相矛盾的终版和截面证据也必须拒绝。离线校验以收到的件为依据。

原 `exchange.intake.accept(db, item) -> int` 接纳 V1 或 V2，保留实际收到的完整字节。相同字节重交沿用实收号，V2 实收回执的 `revision_id` 为终版。坏件报 `ValueError`，无新增实收。白班库只需用于发行。

## 核账和领取

`settlement.audit.review_notes(package, notes) -> list[dict]` 只接收 V2 件字节和备注列表，独立校验件，无需任一数据库。每项是含 `batch_id`、`revision_id`、`left`、`right`、`text` 的字典。左右字段为实际试片号或上述边界值，正文为字符串并原样保留。每个结果形如 `{'note': 原备注字典, 'status': 'placed', 'final_cut': 2}`。存续时给出终版零基切口。已拆时 `status` 为 `'review'` 且 `final_cut` 为 `None`。次序和重复项照收。有效件可交空列表，结果为 `[]`。错批、区间外或无效观察、当时不存在的夹位、无效备注和坏件均报 `ValueError`，整单没有结果。

原 `settlement.publish.sign(db, receipt_id, *, notes=None, before_commit=None)` 保持原返回 `(Daybook, SignReceipt)`。V2 必须显式交备注列表，允许空列表。V1 沿原调用签账，将 V1 实收号用于备注签账时报 `ValueError`。V2 从实际实收件核账，沿用终版装夹规则，原备注、逐项裁决、实际件绑定和原签存回执共同提交。`before_commit` 仍为提交前的无参故障接点。输入拒绝或签存异常时，此次没有部分账或回执，先前实收和旧账保留，可以重试。未知实收号沿用 `KeyError`，数据库异常原样传播。

重开夜班库后调用原 `settlement.readback.read(db, book_id)`。除终版装夹明细和原回执外，V2 的 `detail` 增加 `layout_review`，其中 `start_revision`、`end_revision` 为发行起止修订，`results` 为已签存的备注结果列表。领取按号返回固定内容，无需重放。旧 V1 账保留原格式和入口。

## 样例与核验

`clip_cases.py` 提供原接口构造的排程。四片均为同组且各 1 微米，容量为 3 微米。下文的 r0、r1、r2 在调用中使用 `build_history` 返回的实际 `revision_id`。

- `together` 从 `A B C D` 把 B、C 整段移到 A 前。r0 的 B|C 归到 `B C A D` 的切口 1，r0 的 A|B 待复核。终版装夹为 B C A、D，各 3、1 微米。
- `three_observations` 从 `A B C D` 把 B 搬到 D 后得到 `A C D B`，再移回。夜班在断源后以同一件分别提交下面的有效单及无效引用。终版 `A B C D` 的装夹为 A B C、D，各 3、1 微米。
- `detour_between_freezes` 与 `detour_before_freezes` 的首末冻结和 V1 发行都相同。前者两次搬动发生在两次冻结间，初版 B|C 待复核。后者两次搬动发生在首次冻结前，初版 B|C 归到切口 2。

`three_observations` 的有效单及其预期结果可按下例构造，其中 `package` 为该轨迹起止发行件，`r0`、`r1`、`r2` 为三个修订号字符串。

```python
old = dict(batch_id='LOT', revision_id=r0, left='B', right='C', text='旧夹位')
new = dict(batch_id='LOT', revision_id=r2, left='B', right='C', text='终版夹位')
notes = [old, new, old]
expected = [
    dict(note=old, status='review', final_cut=None),
    dict(note=new, status='placed', final_cut=2),
    dict(note=old, status='review', final_cut=None),
]
```

有效单应按上述次序得到 `expected`。单独提交 `dict(old, revision_id=r1)` 作为备注时必须整单拒绝。该轨迹从 r0 引用 `None|A` 可归到终版切口 0，从 r0 引用 `D|None` 须待复核。交换备注顺序后，结果随输入顺序变化。

保留原运行清单 `.pointwise-runtime.json` 的版本 1 和 `cli` 类型，`setup` 为参数数组列表，`verify` 和 `demo` 分别用参数数组登记实际命令。交付的核验入口执行全部原回归及新增联动检查，失败返回非零。演示输出拆后复位的裁决和断源、重开后的领账。签存核验使用原 `before_commit` 接点验证失败无部分新账、随后可签，并核对旧账仍可领取。`python3 -B clip_cases.py` 在当前 V1 基线上核对样例的冻结排列及装夹明细。
