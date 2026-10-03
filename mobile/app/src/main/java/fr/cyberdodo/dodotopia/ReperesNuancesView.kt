package fr.cyberdodo.dodotopia

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.PointF
import android.view.MotionEvent
import android.view.View
import kotlin.math.hypot

/**
 * Les repères des nuances et des outils du dessin, à poser sur l'outil de peinture du jeu, page des nuances ouverte :
 * bouton « palette », bouton retour, flèches précédent et suivant, première et dixième nuance, puis crayon, pot
 * de peinture et Annuler. Même maniement que [ReperesDessinView] : on déplace le repère le plus proche du doigt,
 * sans avoir à poser le doigt dessus.
 */
class ReperesNuancesView(context: Context, val points: List<PointF>, private val noms: Array<String>) : View(context) {
    private val dp = resources.displayMetrics.density
    private val origine = IntArray(2)
    private var saisie = -1
    private var x0 = 0f
    private var y0 = 0f

    private val halo = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 4 * dp; color = 0xCCFFFFFF.toInt()
    }
    private val trait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 2 * dp; color = context.getColor(R.color.c_brand_edge)
    }
    private val fond = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = context.getColor(R.color.c_primary) }
    private val texte = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = context.getColor(R.color.c_primary_ink)
        textSize = 12 * dp
        isFakeBoldText = true
    }
    private val etiquette = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xE6FFFAF1.toInt() }

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(ev: MotionEvent): Boolean {
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                x0 = ev.rawX; y0 = ev.rawY
                saisie = points.indices.minByOrNull { hypot(points[it].x - ev.rawX, points[it].y - ev.rawY) } ?: -1
                invalidate()
            }
            MotionEvent.ACTION_MOVE -> if (saisie >= 0) {
                // Déplacement relatif : le doigt n'a pas besoin d'être sur le repère, donc ne le cache pas.
                points[saisie].offset(ev.rawX - x0, ev.rawY - y0)
                x0 = ev.rawX; y0 = ev.rawY
                invalidate()
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                val droite = (origine[0] + width - 1f).coerceAtLeast(0f)
                val bas = (origine[1] + height - 1f).coerceAtLeast(0f)
                for (p in points) p.set(p.x.coerceIn(0f, droite), p.y.coerceIn(0f, bas))
                saisie = -1
                invalidate()
            }
        }
        return true
    }

    override fun onDraw(canvas: Canvas) {
        getLocationOnScreen(origine)
        val ox = origine[0].toFloat()
        val oy = origine[1].toFloat()
        // Les dix nuances d'une page, réparties entre la première et la dixième.
        for (rang in 0 until Nuancier.COLONNES * Nuancier.LIGNES) {
            val c = Dessin.nuance(points[Etapes.PREMIERE], points[Etapes.DERNIERE], rang)
            for (p in arrayOf(halo, trait)) canvas.drawCircle(c.x - ox, c.y - oy, 9 * dp, p)
        }
        points.forEachIndexed { i, p ->
            val x = p.x - ox
            val y = p.y - oy
            if (i == saisie) {
                canvas.drawLine(x - 40 * dp, y, x + 40 * dp, y, halo)
                canvas.drawLine(x, y - 40 * dp, x, y + 40 * dp, halo)
            }
            canvas.drawCircle(x, y, 7 * dp, fond)
            canvas.drawCircle(x, y, 7 * dp, trait)
            val largeur = texte.measureText(noms[i])
            // L'étiquette (un simple numéro : les repères sont serrés) se met du côté où il reste de la place.
            val gauche = if (x + 14 * dp + largeur > width) x - 14 * dp - largeur else x + 14 * dp
            canvas.drawRoundRect(gauche - 5 * dp, y - 11 * dp, gauche + largeur + 5 * dp, y + 9 * dp, 8 * dp, 8 * dp, etiquette)
            canvas.drawText(noms[i], gauche, y + 4 * dp, texte)
        }
    }
}
