from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 用于 flash 消息

DATABASE = 'database.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    with open('schema.sql', 'r') as f:
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

        # 获取当前最大的物品编号
        max_item_code = conn.execute('SELECT MAX(item_code) FROM items').fetchone()[0]

        # 如果没有物品，则从 "1" 开始
        if max_item_code is None:
            item_code = "1"
        else:
            # 将最大物品编号转换为整数并加 1
            try:
                item_code_int = int(max_item_code) + 1
            except ValueError:
                # 如果最大物品编号不是整数，则从 "1" 开始
                item_code_int = 1
            # 将新的物品编号格式化为字符串
            item_code = str(item_code_int)

        conn.execute('INSERT INTO items (item_code, item_name, item_spec) VALUES (?, ?, ?)',
                     (item_code, item_name, item_spec))
        conn.commit()
        conn.close()
        return redirect(url_for('items'))
    return render_template('add_item.html')


@app.route('/items')
def items():
    conn = get_db_connection()
    items = conn.execute('SELECT * FROM items').fetchall()
    conn.close()
    return render_template('items.html', items=items)

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
    
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        if form_type == 'in':
            # 处理入库逻辑
            item_id = request.form['item_id']
            inbound_qty = request.form['inbound_qty']
            inbound_date = request.form['inbound_date']
            warehouse_number = request.form['warehouse_number']
            shelf_number = request.form['shelf_number']
            layer_number = request.form['layer_number']
            sn_code = request.form.get('sn_code')  # 获取 SN 码

            
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
            
            conn.execute('INSERT INTO inbound (item_id, inbound_qty, inbound_date, location_id, sn_code) VALUES (?, ?, ?, ?, ?)',  # 插入 SN 码
                         (item_id, inbound_qty, inbound_date, location_id, sn_code))
            conn.commit()
            conn.close()
            return redirect(url_for('inbound_records'))
        
        elif form_type == 'out':
            # 处理出库逻辑
            item_id = request.form['item_id']
            outbound_qty = int(request.form['outbound_qty'])  # 将出库数量转换为整数
            outbound_person = request.form['outbound_person']
            outbound_purpose = request.form['outbound_purpose']
            outbound_date = request.form['outbound_date']
            sn_code = request.form.get('sn_code')  # 获取 SN 码
            
            try:
                location_id = request.form['location_id']
            except KeyError:
                flash('请选择出库位置！', 'error')
                return redirect(url_for('add_stock'))
            
            conn = get_db_connection()

            # 获取当前库存数量
            stock_info = conn.execute('''
                SELECT 
                    IFNULL((SELECT SUM(COALESCE(inbound_qty, 0)) FROM inbound WHERE item_id = ?), 0) -
                    IFNULL((SELECT SUM(COALESCE(outbound_qty, 0)) FROM outbound WHERE item_id = ?), 0) AS stock
            ''', (item_id, item_id)).fetchone()
            
            if stock_info is None or stock_info['stock'] is None:
                flash('该物品无库存！', 'error')
                conn.close()
                return redirect(url_for('add_stock'))
            
            current_stock = stock_info['stock']

            # 限制出库数量
            #if outbound_qty > current_stock:
                #flash(f'出库数量超过库存！已将出库数量限制为 {current_stock}', 'warning')  # 提示信息
                #outbound_qty = current_stock

            
            conn.execute('INSERT INTO outbound (item_id, outbound_qty, outbound_person, outbound_purpose, outbound_date, location_id, sn_code) VALUES (?, ?, ?, ?, ?, ?, ?)',  # 插入 SN 码
                         (item_id, outbound_qty, outbound_person, outbound_purpose, outbound_date, location_id, sn_code))
            conn.commit()
            conn.close()
            return redirect(url_for('outbound_records'))
    
    return render_template('add_stock.html', all_items=all_items, stocked_items=stocked_items, locations=locations, selected_item_id=item_id)

@app.route('/add_stock_in', methods=['POST'])
def add_stock_in():
    if request.method == 'POST':
        item_id = request.form['item_id']
        inbound_qty = request.form['inbound_qty']
        inbound_date = request.form['inbound_date']
        warehouse_number = request.form['warehouse_number']
        shelf_number = request.form['shelf_number']
        layer_number = request.form['layer_number']
        sn_code = request.form['sn_code'] # 获取SN码

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

        conn.execute('INSERT INTO inbound (item_id, inbound_qty, inbound_date, location_id, sn_code) VALUES (?, ?, ?, ?, ?)', # 插入SN码
                     (item_id, inbound_qty, inbound_date, location_id, sn_code))
        conn.commit()
        conn.close()
        return redirect(url_for('inbound_records'))
    return redirect(url_for('add_stock'))


@app.route('/add_stock_out', methods=['POST'])
def add_stock_out():
    if request.method == 'POST':
        item_id = request.form['item_id']
        outbound_qty = request.form['outbound_qty']
        outbound_person = request.form['outbound_person']
        outbound_purpose = request.form['outbound_purpose']
        outbound_date = request.form['outbound_date']
        sn_code = request.form['sn_code'] # 获取SN码

        try:
            location_id = request.form['location_id']
        except KeyError:
            flash('请选择出库位置！', 'error')  # 使用 flash 消息
            return redirect(url_for('add_stock'))

        conn = get_db_connection()
        conn.execute('INSERT INTO outbound (item_id, outbound_qty, outbound_person, outbound_purpose, outbound_date, location_id, sn_code) VALUES (?, ?, ?, ?, ?, ?, ?)', # 插入SN码
                     (item_id, outbound_qty, outbound_person, outbound_purpose, outbound_date, location_id, sn_code))
        conn.commit()
        conn.close()
        return redirect(url_for('outbound_records'))
    return redirect(url_for('add_stock'))

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
    conn = get_db_connection()
    sns = [row[0] for row in conn.execute('SELECT sn_code FROM inbound WHERE item_id = ? AND sn_code IS NOT NULL', (item_id,)).fetchall()]
    conn.close()
    return jsonify(sns)


@app.route('/stock_report')
def stock_report():
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
    ''').fetchall()
    outbound_records = conn.execute('''
        SELECT outbound.*, items.item_name, items.item_spec, outbound_person, outbound_purpose, outbound_date, locations.warehouse_number, locations.shelf_number, locations.layer_number, outbound.sn_code  -- 添加 sn_code
        FROM outbound
        JOIN items ON outbound.item_id = items.id
        JOIN locations ON outbound.location_id = locations.id
    ''').fetchall()
    conn.close()
    return render_template('stock_report.html', inventory=inventory, inbound_records=inbound_records, outbound_records=outbound_records)


@app.route('/inbound_records')
def inbound_records():
    return redirect(url_for('stock_report'))


@app.route('/outbound_records')
def outbound_records():
   return redirect(url_for('stock_report'))

@app.route('/inventory')
def inventory():
    return redirect(url_for('stock_report'))


if __name__ == '__main__':
    #init_db()
    app.run(debug=True)
