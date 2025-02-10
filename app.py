from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3
import json  # 导入 json 模块
import openpyxl  # 导入 openpyxl 模块

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 用于 flash 消息

DATABASE = 'database.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    with open('schema.sql', 'r', encoding='utf-8') as f:  # 指定编码为 utf-8
        conn.executescript(f.read())
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/add_item', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        item_name = request.form['item_name']
        item_spec = request.form['item_spec']
        conn = get_db_connection()

        # 检查物品名称和规格是否已存在
        existing_item = conn.execute('SELECT * FROM items WHERE item_name = ? AND item_spec = ?', (item_name, item_spec)).fetchone()
        if existing_item:
            conn.close()
            return jsonify({'status': 'error', 'message': '物品已注册，请勿重复添加！'})

        # 获取当前最大的物品编号
        max_item_code = conn.execute('SELECT MAX(item_code) FROM items').fetchone()[0]

        # 如果没有物品，则从 "1" 开始
        if max_item_code is None:
            item_code = 1
        else:
            # 将最大物品编号转换为整数并加 1
            item_code = int(max_item_code) + 1

        try:
            conn.execute('INSERT INTO items (item_code, item_name, item_spec) VALUES (?, ?, ?)',
                         (item_code, item_name, item_spec))
            conn.commit()
            conn.close()
            return jsonify({'status': 'success', 'message': '物品添加成功！'})
        except Exception as e:
            conn.rollback()  # 回滚事务
            conn.close()
            return jsonify({'status': 'error', 'message': str(e)})

    return render_template('add_item.html')

@app.route('/batch_add_item', methods=['POST'])
def batch_add_item():
    try:
        # 检查是否有文件上传
        if 'excel_file' not in request.files:
            return jsonify({'status': 'error', 'message': '没有选择文件！'})

        excel_file = request.files['excel_file']

        # 检查文件是否为空
        if excel_file.filename == '':
            return jsonify({'status': 'error', 'message': '文件名为空！'})

        # 检查文件类型是否正确
        if not excel_file.filename.endswith(('.xlsx', '.xls')):
            return jsonify({'status': 'error', 'message': '文件类型不正确，请选择 Excel 文件！'})

        # 读取 Excel 文件
        workbook = openpyxl.load_workbook(excel_file)
        sheet = workbook.active

        conn = get_db_connection()

        # 获取当前最大的物品编号
        max_item_code = conn.execute('SELECT MAX(item_code) FROM items').fetchone()[0]

        # 如果没有物品，则从 "1" 开始
        if max_item_code is None:
            item_code = 1
        else:
            # 将最大物品编号转换为整数并加 1
            item_code = int(max_item_code) + 1

        # 从第二行开始读取数据（跳过表头）
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row[0] is not None:  # 只要物品名称不为空就处理
                item_name = str(row[0])
                item_spec = str(row[1]) if row[1] is not None else ""  # 如果物品规格为空，则设置为空字符串

                # 检查物品名称和规格是否已存在
                existing_item = conn.execute('SELECT * FROM items WHERE item_name = ? AND item_spec = ?', (item_name, item_spec)).fetchone()
                if existing_item:
                    continue  # 如果已存在，则跳过

                # 插入数据
                conn.execute('INSERT INTO items (item_code, item_name, item_spec) VALUES (?, ?, ?)',
                             (item_code, item_name, item_spec))

                # 递增物品编号
                item_code += 1

        conn.commit()
        conn.close()

        return jsonify({'status': 'success', 'message': '物品批量添加成功！'})

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/add_stock', methods=['GET', 'POST'])
def add_stock():
    conn = get_db_connection()

    # 获取所有物品（用于入库）
    all_items = conn.execute('SELECT * FROM items').fetchall()

    # 获取有库存的物品（用于出库）
    stocked_items = conn.execute('''
        SELECT items.*
        FROM items
        WHERE items.id IN (
            SELECT subquery.id
            FROM (
                SELECT items.id,
                    IFNULL((SELECT SUM(COALESCE(inbound_qty, 0)) FROM inbound WHERE item_id = items.id), 0) -
                    IFNULL((SELECT SUM(COALESCE(outbound_qty, 0)) FROM outbound WHERE item_id = items.id), 0) AS stock
                FROM items
            ) AS subquery
            WHERE stock > 0
        )
    ''').fetchall()

    # 动态加载位置（用于出库）
    locations = []
    item_id = request.args.get('item_id')  # 获取物品ID
    if item_id:
        locations = conn.execute('''
            SELECT l.id, l.warehouse_number, l.shelf_number, l.layer_number
            FROM locations l
            WHERE l.id IN (
                SELECT i.location_id
                FROM inbound i
                WHERE i.item_id = ?
                GROUP BY i.location_id
                HAVING SUM(i.inbound_qty) > (
                    SELECT IFNULL(SUM(o.outbound_qty), 0)
                    FROM outbound o
                    WHERE o.item_id = ? AND o.location_id = i.location_id
                )
            )
        ''', (item_id, item_id)).fetchall()

    conn.close()

    return render_template('add_stock.html', all_items=all_items, stocked_items=stocked_items, locations=locations, selected_item_id=item_id)


@app.route('/add_stock_in_api', methods=['POST'])
def add_stock_in_api():
    conn = None  # 初始化 conn 变量
    try:
        item_id = request.form['item_id']
        inbound_qty = int(request.form['inbound_qty'])
        inbound_date = request.form['inbound_date']
        warehouse_number = request.form['warehouse_number']
        shelf_number = request.form['shelf_number']
        layer_number = request.form['layer_number']
        sn_codes_json = request.form['sn_codes']  # 获取 SN 码 JSON 字符串

        # 检查 sn_codes_json 是否为空字符串
        if not sn_codes_json:
            sn_codes = []  # 如果为空，则设置为空列表
        else:
            sn_codes = json.loads(sn_codes_json)  # 解析 SN 码数组

        conn = get_db_connection()

        # 检查位置是否存在，如果不存在则创建
        location = conn.execute('SELECT id FROM locations WHERE warehouse_number = ? AND shelf_number = ? AND layer_number = ?',
                                (warehouse_number, shelf_number, layer_number)).fetchone()
        if location is None:
            conn.execute('INSERT INTO locations (warehouse_number, shelf_number, layer_number) VALUES (?, ?, ?)',
                         (warehouse_number, shelf_number, layer_number))
            conn.commit()
            location_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        else:
            location_id = location['id']

        # 如果 SN 码列表为空，则插入一条记录，数量为手动输入的数量，SN 码为 None
        if not sn_codes:
            conn.execute('INSERT INTO inbound (item_id, inbound_qty, inbound_date, location_id, sn_code) VALUES (?, ?, ?, ?, ?)',
                         (item_id, inbound_qty, inbound_date, location_id, None))
        else:
            # 处理 "已损毁" SN 码
            damaged_count = sn_codes.count('已损毁')
            if '已损毁' in sn_codes:
                sn_codes = [code for code in sn_codes if code != '已损毁']

            # 插入 "已损毁" 记录
            if damaged_count > 0:
                conn.execute('INSERT INTO inbound (item_id, inbound_qty, inbound_date, location_id, sn_code) VALUES (?, ?, ?, ?, ?)',
                             (item_id, damaged_count, inbound_date, location_id, '已损毁'))

            # 循环插入每个 SN 码对应的入库记录
            for sn_code in sn_codes:
                # 允许 sn_code 为空
                if not sn_code:
                    sn_code = None  # 或者 sn_code = ""
                conn.execute('INSERT INTO inbound (item_id, inbound_qty, inbound_date, location_id, sn_code) VALUES (?, ?, ?, ?, ?)',
                             (item_id, 1, inbound_date, location_id, sn_code))  # 每个 SN 码对应一个入库记录，数量为 1

        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'message': '物品入库成功！'})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            conn.close()

@app.route('/add_stock_out_api', methods=['POST'])
def add_stock_out_api():
    conn = None  # 初始化 conn 变量
    try:
        item_id = request.form['item_id']
        outbound_qty = int(request.form['outbound_qty'])
        outbound_person = request.form['outbound_person']
        outbound_purpose = request.form['outbound_purpose']
        outbound_date = request.form['outbound_date']
        sn_code = request.form.get('sn_code')

        try:
            location_id = request.form['location_id']
        except KeyError:
            return jsonify({'status': 'error', 'message': '请选择出库位置！'})

        conn = get_db_connection()

        # 获取当前库存数量
        stock_info = conn.execute('''
            SELECT
                IFNULL((SELECT SUM(COALESCE(inbound_qty, 0)) FROM inbound WHERE item_id = ?), 0) -
                IFNULL((SELECT SUM(COALESCE(outbound_qty, 0)) FROM outbound WHERE item_id = ?), 0) AS stock
        ''', (item_id, item_id)).fetchone()

        if stock_info is None or stock_info['stock'] is None:
            conn.close()
            return jsonify({'status': 'error', 'message': '该物品无库存！'})

        current_stock = stock_info['stock']

        # 限制出库数量
        if outbound_qty > current_stock:
            #outbound_qty = current_stock
            return jsonify({'status': 'error', 'message': '该物品库存不足！'})
        else:
            conn.execute('INSERT INTO outbound (item_id, outbound_qty, outbound_person, outbound_purpose, outbound_date, location_id, sn_code) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (item_id, outbound_qty, outbound_person, outbound_purpose, outbound_date, location_id, sn_code))
            conn.commit()
            conn.close()
            return jsonify({'status': 'success', 'message': '物品出库成功！'})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            conn.close()

@app.route('/get_locations')
def get_locations():
    item_id = request.args.get('item_id')
    conn = get_db_connection()
    locations = conn.execute('''
        SELECT l.id, l.warehouse_number, l.shelf_number, l.layer_number
        FROM locations l
        WHERE l.id IN (
            SELECT i.location_id
            FROM inbound i
            WHERE i.item_id = ?
            GROUP BY i.location_id
            HAVING SUM(i.inbound_qty) > (
                SELECT IFNULL(SUM(o.outbound_qty), 0)
                FROM outbound o
                WHERE o.item_id = ? AND o.location_id = i.location_id
            )
        )
    ''', (item_id, item_id)).fetchall()
    conn.close()
    location_list = []
    for location in locations:
        location_list.append({
            'id': location['id'],
            'warehouse_number': location['warehouse_number'],
            'shelf_number': location['shelf_number'],
            'layer_number': location['layer_number']
        })
    return jsonify(location_list)

@app.route('/get_sns')  # 新的路由
def get_sns():
    item_id = request.args.get('item_id')
    location_id = request.args.get('location_id') # 获取 location_id

    conn = get_db_connection()
    # 修改查询: 确保只返回特定 item_id 和 location_id 的非空 SN 码
    sns = [row[0] for row in conn.execute('''
        SELECT sn_code FROM inbound
        WHERE item_id = ? AND location_id = ? AND sn_code IS NOT NULL
    ''', (item_id, location_id)).fetchall()]
    conn.close()
    return jsonify(sns)


@app.route('/check_duplicate_sn', methods=['POST'])
def check_duplicate_sn():
    data = request.get_json()
    item_id = data['item_id']
    sn_code = data['sn_code']

    conn = get_db_connection()
    existing_sn = conn.execute('''
        SELECT sn_code FROM inbound
        WHERE item_id = ? AND sn_code = ?
        AND NOT EXISTS (SELECT 1 FROM outbound WHERE outbound.sn_code = inbound.sn_code)
    ''', (item_id, sn_code)).fetchone()
    conn.close()

    is_duplicate = existing_sn is not None
    return jsonify({'is_duplicate': is_duplicate})

@app.route('/stock_report')
def stock_report():
    table_select = request.args.get('table_select', 'inventory')  # 获取选择的表单，默认为 'inventory'
    page = request.args.get('page', 0, type=int)  # 获取页码，默认为 0

    conn = get_db_connection()
    inventory = conn.execute('''
        SELECT
            items.item_name,
            items.item_spec,
            locations.warehouse_number || '号仓库' || locations.shelf_number || '号货架' || locations.layer_number || '层' AS location,
            SUM(COALESCE(inbound.inbound_qty, 0)) - COALESCE((
                SELECT SUM(COALESCE(outbound.outbound_qty, 0))
                FROM outbound
                WHERE outbound.item_id = items.id AND outbound.location_id = locations.id
            ), 0) AS stock
        FROM
            items
        LEFT JOIN
            inbound ON items.id = inbound.item_id
        LEFT JOIN
            locations ON inbound.location_id = locations.id
        GROUP BY
            items.item_name, items.item_spec, location
        HAVING
            stock != 0
        ORDER BY
            items.item_name, items.item_spec, location;
    ''').fetchall()
    inbound_records = conn.execute('''
        SELECT inbound.*, items.item_name, items.item_spec, locations.warehouse_number, locations.shelf_number, locations.layer_number, inbound.sn_code  -- 添加 sn_code
        FROM inbound
        JOIN items ON inbound.item_id = items.id
        JOIN locations ON inbound.location_id = locations.id
        ORDER BY inbound.id DESC
    ''').fetchall()
    outbound_records = conn.execute('''
        SELECT outbound.*, items.item_name, items.item_spec, outbound_person, outbound_purpose, outbound_date, locations.warehouse_number, locations.shelf_number, locations.layer_number, outbound.sn_code  -- 添加 sn_code
        FROM outbound
        JOIN items ON outbound.item_id = items.id
        JOIN locations ON outbound.location_id = locations.id
        ORDER BY outbound.id DESC
    ''').fetchall()
    items = conn.execute('SELECT * FROM items ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('stock_report.html', inventory=inventory, inbound_records=inbound_records, outbound_records=outbound_records, items=items, table_select=table_select, page=page)

@app.route('/inbound_records')
def inbound_records():
    return redirect(url_for('stock_report'))

@app.route('/outbound_records')
def outbound_records():
   return redirect(url_for('stock_report'))

#@app.route('/inventory')
#def inventory():
#    return redirect(url_for('stock_report'))

@app.route('/delete_inbound_record/<int:id>', methods=['POST'])
def delete_inbound_record(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM inbound WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('stock_report', table_select='inbound'))

@app.route('/delete_outbound_record/<int:id>', methods=['POST'])
def delete_outbound_record(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM outbound WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('stock_report', table_select='outbound'))

@app.route('/delete_item/<int:id>', methods=['POST'])
def delete_item(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM items WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('stock_report', table_select='items'))

if __name__ == '__main__':
    #init_db()
    app.run(debug=True)
