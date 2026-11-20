# 材料试片排程交班 V1

送样组提交带出处的具名试片清单。白班调整加工顺序，选定当时的夹具规格并冻结。夜班在独立库实收固定件，复算装夹并签账。操作员在重开夜班库后仍能按账号领取当时的明细和回执。

## 运行

需要 Python 3.11，依赖均来自标准库。进入项目根目录执行正常回归。

```sh
python3 -B check_project.py
```

`check_project.py` 由运行平台提供。演示使用独立临时库，实算并打印重开后的领取明细。

```sh
python3 -B demo.py
```

## 两班操作

业务 API 接收空闲的 `sqlite3.Connection`，写入入口自行提交，调用时请先结束外层事务。以默认连接设置或 `isolation_level=None` 打开各自的库。白班和夜班各用自己的数据库文件。

1. 白班调用 `intake.batches.init_intake`、`layout.drafts.init_layout` 和 `fixture.profiles.init_fixtures`。`admit(db, batch_id, source, rows)` 接收按来料顺序给出的记录列表，每行含 `specimen_id`、`group`、`thickness_um`。返回 `Batch` 和其中的来料回执。`load_batch(db, batch_id)` 读取同一实收事实。
2. `arrange(db, batch_id)` 取得原序开排的 `Draft`，已有草稿时取当前草稿。`arrange(db, batch_id, SegmentMove(start, stop, destination))` 编辑已开的草稿。`layout.drafts.load_draft(db, draft_id)` 和 `layout.edit_log.list_draft_edits(db, draft_id)` 读取当前次序和实际生效的 V1 编辑记录。
3. `fixture.profiles.register_profile(db, name, capacity_um, allowed_groups)` 登记当前夹具规格。同名登记只更新当前规格。`layout.freeze.freeze(db, draft_id, profile_name)` 返回固定修订和装夹试算。用 `layout.revisions.load_revision(db, revision_id)` 领取原修订。
4. `exchange.issue.issue(db, revision_id)` 生成单版 V1 字节，随后可关闭白班库。
5. 夜班调用 `exchange.receipts.init_exchange` 和 `settlement.entries.init_settlement`。`exchange.intake.accept(db, item)` 返回实收号。`exchange.receipts.load_received_item(db, receipt_id)` 返回原字节和实收回执。
6. `settlement.audit.audit_received_item(db, receipt_id)` 可按隔离实收件试算核对。实际计算使用件内加工序、厚度、组别和冻结规格。
7. `settlement.publish.sign(db, receipt_id)` 一次提交并返回 `(Daybook, SignReceipt)`。每次成功签账产生新账号，交班件重交的去重规则适用于实收。签存提供可选的 `before_commit` 无参回调供提交前故障检查，回调抛出的异常会使此次签存回滚。
8. `settlement.readback.read(db, book_id)` 返回固定账、原回执及操作员明细，并登记一次领取。重开并再次初始化后可按同一账号复领。

## 业务规则

身份、组别、规格名称和出处使用非空文本，精确比较。厚度和容量为正整数微米，布尔、浮点、空值和数字字符串无效。合法空清单可完成全流程。编排使用移除前的切口编号，搬动区间采用零基半开坐标。首尾切口可用，搬段端点切口保持原序和原编辑记录，段内切口、越界和空段拒绝。加工序必须是来料身份的精确排列。

单片必须适用夹具且能单独容纳。沿加工序逐片累加，同组且加入后未超容则沿用当前装夹，换组或超容时另开装夹。只在相邻装夹组别不同时计一次换型。容量 10 微米、加工序为同组 4、6、3 微米再接另一组 2 微米时，装夹总厚度分别为 10、3、2 微米，换型一次。计算使用整数，数组及明细沿业务顺序保存。

件的目录承诺批号、修订号和规范载荷摘要。规范载荷以排序键和无多余空白的 UTF-8 JSON 表示。实收按实际全件字节区分，重新接纳相同字节返回原号。签账读取实际收到的件，领取读取已经签下的结果。

非法输入、不可装夹事实和无效件报 `ValueError`，未知批次、草稿、规格、修订、实收号和账号报 `KeyError`。SQLite 写入异常保留原类型。失败的收料、冻结、接件及签账请求没有部分提交。每个初始化入口只建缺失结构，已登记或签存的内容在反复初始化后仍可读取。
