{
    'name': 'JAGUEN - Portal de Lealtad',
    'summary': 'Los clientes ven en su portal el progreso y las recompensas de los programas de lealtad',
    'description': """
Portal de Lealtad JAGUEN
=========================

Agrega una tarjeta "Mis Puntos" en el portal de clientes (Mi cuenta) con una
pantalla principal de 3 botones, uno por grupo de programas de lealtad:

* Programa de Recompensa (JAGUEN Starter en onboarding, o Rebate Anual una
  vez capturado el "Objetivo del año" del cliente) - barra de progreso y
  escalera de tramos (Desbloqueado / Siguiente / Bloqueado).
* Mi Primer Pedido de $X - checklist Hecho / Pendiente (cada tramo es un
  evento de una sola vez, no acumulable).
* Mi Primer Pedido por Línea - checklist Hecho / Pendiente por línea de
  producto.

No cambia la lógica de acumulación de puntos: lee directamente los
programas de lealtad nativos de Odoo (Ventas > Descuentos y programas de
lealtad) y las tarjetas de lealtad (loyalty.card) del propio cliente.
Agrega dos campos: 'x_jaguen_loyalty_group' en loyalty.program (para
clasificar cada programa en uno de los 3 botones) y
'x_objetivo_anual_programa2' en res.partner (el interruptor manual entre
JAGUEN Starter y Rebate Anual).

Incluye además, como datos del propio módulo (se crean solos al instalar
o reinstalar en cualquier base, sin pasos manuales): los 23 programas de
lealtad de la Política de Incentivos Comerciales JAGUEN (JAGUEN Starter,
Rebate Anual, Mi Primer Pedido de $X ×10, Mi Primer Pedido por Línea ×11),
el campo "Objetivo del año", y las automatizaciones de negocio (activar
Programa 2 al capturar el objetivo, bloquear Programa 2 si no corresponde,
aviso por correo 2 semanas antes del fin de onboarding, aviso interno a
los 4 meses, y la guardia de "solo una vez por cliente" para los vales de
primer pedido).

Rebate Anual por ejercicio (oct/2026): además del programa original
"Rebate Anual" (sin fecha de corte, ya no se usa en producción), se
crean los programas independientes "Rebate Anual 2027", "2028" y "2029"
(ver data/loyalty_data_rebate_anual_anios.xml) - cada año tiene su propio
acumulado desde cero, trazable para siempre. El cambio de año (apagar
portal_visible del programa del año que termina, encender el del año
que empieza, y migrar a cada cliente que ya estaba en Rebate a una
tarjeta nueva en 0 puntos) es 100% automático vía una tarea programada
que corre cada 1 de enero (cron_cambio_anio_rebate_anual, ver
data/automation_data.xml) - no requiere intervención manual, siempre y
cuando el programa "Rebate Anual <año>" del año que sigue ya exista
creado con tiempo.

Candado de pago (oct/2026): los puntos de los 4 programas no cuentan para
el cliente sino hasta que la factura correspondiente esté 100% pagada
(payment_state = 'paid'), no solo confirmada. Ver
models/loyalty_payment_gate.py para la mecánica completa (se "congelan"
los puntos recién otorgados al confirmar un pedido, y se liberan en
proporción conforme cada factura de ese pedido se va pagando). Incluye
también el manejo de cancelación de un pedido ya confirmado (deshace el
congelamiento antes de que corra la resta nativa de sale_loyalty, para
que el saldo de la tarjeta no quede en negativo), la resta de puntos al
publicar una nota de crédito (incluso contra la factura de un pedido ya
cancelado), y evita que cancelar y reactivar (reset a borrador +
reconfirmar) un pedido pueda llegar a duplicar los puntos otorgados.

Candado de Términos y Condiciones: antes de ver cualquier programa, el
cliente debe pasar por /my/loyalty/terminos y contestar dos casillas
independientes (puede marcar una, las dos, o ninguna) - "Incentivos al
comprador" (JAGUEN Starter, Mi Primer Pedido de $X, Mi Primer Pedido por
Línea, y la tarjeta de regalo dentro de Rebate Anual) y "Rebate Anual"
(la nota de crédito a la empresa). Dentro de Rebate Anual, la escalera
muestra por separado la nota de crédito (empresa) y la tarjeta de regalo
(comprador) - el segundo renglón desaparece si el cliente no aceptó
incentivos al comprador, aunque sí haya aceptado el rebate. El cliente
puede volver a esa pantalla cuando quiera para cambiar su respuesta. La
página de términos completos (/my/loyalty/terminos/completos) está
redactada en formato de cláusulas numeradas, en el mismo estilo que los
Términos y Condiciones generales de www.jaguen.com, con el domicilio
fiscal real de JAGUEN (Calle Riada #6, Hermosillo, Sonora, C.P. 83147),
la mecánica de cada programa (cláusula 2) y la elegibilidad detallada -
excluye gobierno, dependencias, licitaciones y portales de compras
gubernamentales, además de cuentas privadas cuyas propias políticas de
transparencia lo prohíban (cláusula 4).

Agrega una sección "Portal de Lealtad (Mis Puntos)" en el formulario de
Contactos (justo arriba de las pestañas), donde se ve y se puede editar
el Objetivo del año y las dos casillas de aceptación de cada cliente, y
se ve (de solo lectura) si ya contestó la pantalla de Términos y cuándo.

Cláusula 2 de los TyC completos de Rewards (oct/2026): se agrega la
mención explícita de que los puntos se habilitan y aparecen reflejados
en la cuenta del Cliente hasta que la factura correspondiente está
pagada en su totalidad - ya estaba en el texto de "El Portal" pero no en
el documento legal de Términos y Condiciones.

    """,
    'version': '18.0.20.0.8',
    'category': 'Sales/Loyalty',
    'author': 'JAGUEN',
    'license': 'LGPL-3',
    'depends': ['portal', 'loyalty', 'sale_loyalty', 'website_sale_loyalty', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/loyalty_data.xml',
        'data/loyalty_data_rebate_anual_anios.xml',
        'data/automation_data.xml',
        'views/portal_templates.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
