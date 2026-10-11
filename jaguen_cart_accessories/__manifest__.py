{
    'name': 'JAGUEN - Sugerencias en la tienda (accesorios y alternativos)',
    'summary': 'Accesorios del carrito con rotacion semanal y orden propio de los productos alternativos',
    'description': """
Accesorios sugeridos en el carrito (JAGUEN)
===========================================

Reemplaza la lista fija de "Productos accesorios" de cada producto por una
seleccion calculada al momento de mostrar el carrito de la tienda en linea.
No modifica ni lee los campos de accesorios de los productos, y no guarda
datos: todo se calcula en el momento.

Siempre se ofrecen 6 productos publicados, sin repetir y sin lo que ya esta en
el carrito:

1. Producto ancla (1): 000374; si ya esta en el carrito, 000088; si tambien,
   005072. Si los tres ya estan en el carrito, ese espacio lo ocupa un
   producto de las reglas 3.
2. Exploracion (2): dos productos de dos lineas distintas entre si (categoria
   principal de eCommerce) y distintas a las que ya hay en el carrito.
3. El resto (3, o 4 si no hubo ancla):
   * Con sesion iniciada: lo que ese cliente (su empresa) ha comprado mas
     veces en pedidos confirmados, y que no esta en el carrito.
   * Si faltan, o si no hay sesion iniciada: productos al azar de las mismas
     categorias de eCommerce que lo que hay en el carrito. Si aun faltan,
     de la misma linea y, al final, de todo el catalogo publicado.

Lo "al azar" cambia cada semana (semana ISO) y se mantiene estable durante la
semana para el mismo carrito. Con el parametro del sistema
``jaguen_cart_accessories.week_offset`` (entero, por defecto 0) se puede
adelantar o atrasar la semana para forzar otra rotacion.

Orden de los productos alternativos
-----------------------------------
Odoo muestra los alternativos del producto en orden alfabetico. Este modulo guarda
la posicion de cada alternativo (modelo jaguen.alternative.rank) y la tienda los
muestra en ese orden, para que los 4 primeros (los de mas visibilidad: el mismo
modelo en otros colores, complementos) no cambien. Los alternativos sin posicion
se muestran al final, en orden alfabetico. Las posiciones se cargan con una
importacion (Ajustes > tecnico) y no cambian los alternativos de cada producto.

Solo se consideran productos publicados en el sitio, vendibles, con un unico
variante (no requieren elegir atributos) y con precio mayor a $1.
""",
    'version': '18.0.1.1.0',
    'category': 'Website/Website',
    'author': 'JAGUEN',
    'license': 'LGPL-3',
    'depends': ['website_sale'],
    'data': ['security/ir.model.access.csv'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
