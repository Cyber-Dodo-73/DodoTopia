package fr.cyberdodo.dodotopia

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.PointF
import android.view.View

/** Viseur déplaçable : le point visé est le centre exact de la vue. */
class ViseurView(context: Context) : View(context) {
    private val dp = resources.displayMetrics.density
    private val halo = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 5 * dp; color = 0xCCFFFFFF.toInt()
    }
    private val trait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 2 * dp; color = context.getColor(R.color.c_brand_edge)
    }
    private val voile = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0x33E8A531 }
    private val point = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = context.getColor(R.color.c_danger) }

    override fun onDraw(canvas: Canvas) {
        val cx = width / 2f
        val cy = height / 2f
        val rayon = minOf(cx, cy) - 4 * dp
        val trou = 8 * dp
        canvas.drawCircle(cx, cy, rayon, voile)
        // Halo blanc sous le trait brun : lisible sur un fond clair comme sur un fond sombre.
        for (p in arrayOf(halo, trait)) {
            canvas.drawCircle(cx, cy, rayon, p)
            canvas.drawLine(cx - rayon, cy, cx - trou, cy, p)
            canvas.drawLine(cx + trou, cy, cx + rayon, cy, p)
            canvas.drawLine(cx, cy - rayon, cx, cy - trou, p)
            canvas.drawLine(cx, cy + trou, cx, cy + rayon, p)
        }
        canvas.drawCircle(cx, cy, 2.5f * dp, point)
    }
}

/**
 * Calque plein écran, non tactile, qui montre les repères déjà placés pendant qu'on en ajoute.
 * Les repères sont en coordonnées d'écran : on retranche la position réelle du calque,
 * qui n'est pas forcément (0, 0) selon les encoches et les barres système.
 */
class ReperesView(context: Context, private val reperes: List<PointF>) : View(context) {
    private val dp = resources.displayMetrics.density
    private val fond = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xD9E8A531.toInt() }
    private val bord = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 2 * dp; color = context.getColor(R.color.c_brand_edge)
    }
    private val texte = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = context.getColor(R.color.c_primary_ink)
        textAlign = Paint.Align.CENTER
        textSize = 13 * dp
        isFakeBoldText = true
    }
    private val origine = IntArray(2)

    override fun onDraw(canvas: Canvas) {
        getLocationOnScreen(origine)
        val rayon = 13 * dp
        reperes.forEachIndexed { i, p ->
            val x = p.x - origine[0]
            val y = p.y - origine[1]
            canvas.drawCircle(x, y, rayon, fond)
            canvas.drawCircle(x, y, rayon, bord)
            canvas.drawText((i + 1).toString(), x, y - (texte.ascent() + texte.descent()) / 2, texte)
        }
    }
}
