package fr.cyberdodo.dodotopia

import android.animation.ValueAnimator
import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.PointF
import android.graphics.RectF
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import android.view.animation.LinearInterpolator
import kotlin.math.hypot

/**
 * Calque plein écran du calibrage : une pastille par touche de l'instrument, à faire glisser sur le jeu.
 * Déplacer la première ou la dernière pastille d'une rangée répartit les autres entre les deux ;
 * une pastille du milieu se règle seule ; glisser dans le vide déplace toute la grille.
 * Les points sont en coordonnées d'écran (celles que dispatchGesture attend) : on retranche la
 * position réelle du calque, qui n'est pas forcément (0, 0) selon les encoches.
 */
class CalibrageView(
    context: Context,
    val points: List<PointF>,
    private val disposition: Disposition,
    private val noms: Array<String>,
    inverse: Boolean,
) : View(context) {

    /** Rangées graves en bas de l'écran, aiguës en haut : c'est ainsi que le jeu dessine son piano. */
    var inverse = inverse
        private set

    /** Touche mise en avant pendant le test, ou -1. */
    var active = -1
        set(valeur) {
            if (field != valeur) {
                field = valeur
                invalidate()
            }
        }

    private val dp = resources.displayMetrics.density
    private val origine = IntArray(2)
    private var saisie = -1
    private var x0 = 0f
    private var y0 = 0f

    private val ligne = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 2 * dp; color = 0x99FFFFFF.toInt()
    }
    private val fondBout = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = context.getColor(R.color.c_primary) }
    private val fondMilieu = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xE6FFFAF1.toInt() }
    private val fondActif = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = context.getColor(R.color.c_menthe) }
    private val bord = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 2 * dp; color = context.getColor(R.color.c_brand_edge)
    }
    private val croix = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 3 * dp; color = context.getColor(R.color.blanc)
    }
    private val texte = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = context.getColor(R.color.c_primary_ink)
        textAlign = Paint.Align.CENTER
        textSize = 11 * dp
        isFakeBoldText = true
    }

    private fun estBout(i: Int) = disposition.groupes.any { i == it.first || i == it.last }

    /** Vrai pour un dièse. Seul le clavier complet en a : ses touches noires sont posées entre les blanches, en retrait. */
    private fun estNoire(i: Int) = disposition.notes[i] % 12 in NOIRES

    private val aDesNoires = disposition.notes.indices.any(::estNoire)

    /**
     * Écart entre une touche noire et le milieu de ses deux voisines blanches. Relu sur un calibrage
     * existant ; null tant qu'on n'en a pas : il est alors déduit de l'espacement des blanches.
     */
    private var retraitNoires: PointF? = null

    init {
        if (aDesNoires) {
            val i = disposition.notes.indices.first(::estNoire)
            val ecart = PointF(
                points[i].x - (points[i - 1].x + points[i + 1].x) / 2,
                points[i].y - (points[i - 1].y + points[i + 1].y) / 2,
            )
            // Une grille toute neuve a ses pastilles alignées : pas de retrait à relire.
            if (hypot(ecart.x, ecart.y) > 2 * dp) retraitNoires = ecart
        }
    }

    /** Pose la grille de départ comme le jeu dessine ses touches (noires en retrait). Sans effet sur un clavier sans dièses. */
    fun repartirTout() {
        disposition.groupes.forEach(::repartir)
        invalidate()
    }

    /**
     * Répartit les pastilles d'une rangée entre sa première et sa dernière. Sur le clavier complet,
     * ce sont les blanches qui sont espacées régulièrement (il n'y a pas de noire entre mi et fa),
     * et chaque noire se place entre ses deux voisines, en retrait.
     */
    private fun repartir(rangee: IntRange) {
        val a = points[rangee.first]
        val b = points[rangee.last]
        if (!aDesNoires) {
            val n = rangee.last - rangee.first
            for (i in 1 until n) {
                points[rangee.first + i].set(a.x + (b.x - a.x) * i / n, a.y + (b.y - a.y) * i / n)
            }
            return
        }
        val blanches = rangee.filter { !estNoire(it) }
        val n = blanches.size - 1
        blanches.forEachIndexed { rang, i ->
            if (rang in 1 until n) points[i].set(a.x + (b.x - a.x) * rang / n, a.y + (b.y - a.y) * rang / n)
        }
        placerNoires(rangee)
    }

    private fun placerNoires(rangee: IntRange) {
        val a = points[rangee.first]
        val b = points[rangee.last]
        val blanches = rangee.count { !estNoire(it) } - 1
        // Par défaut : vers le haut de l'écran, d'un tiers de l'écart entre deux blanches.
        val retrait = retraitNoires ?: PointF(0f, -hypot(b.x - a.x, b.y - a.y) / blanches.coerceAtLeast(1) / 3)
        for (i in rangee) if (estNoire(i)) {
            points[i].set(
                (points[i - 1].x + points[i + 1].x) / 2 + retrait.x,
                (points[i - 1].y + points[i + 1].y) / 2 + retrait.y,
            )
        }
    }

    /**
     * Échange les rangées graves et aiguës : les lignes dessinées à l'écran ne bougent pas,
     * ce sont les notes qui changent de ligne (et le nombre de pastilles, si les rangées sont inégales).
     */
    fun inverser() {
        val groupes = disposition.groupes
        val lignes = groupes.map {
            PointF(points[it.first].x, points[it.first].y) to PointF(points[it.last].x, points[it.last].y)
        }
        groupes.forEachIndexed { r, rangee ->
            val (a, b) = lignes[groupes.size - 1 - r]
            points[rangee.first].set(a)
            points[rangee.last].set(b)
            repartir(rangee)
        }
        inverse = !inverse
        invalidate()
    }

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(ev: MotionEvent): Boolean {
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                x0 = ev.rawX; y0 = ev.rawY
                var proche = -1
                var distance = 36 * dp
                points.forEachIndexed { i, p ->
                    val d = hypot(p.x - ev.rawX, p.y - ev.rawY)
                    if (d < distance) {
                        distance = d; proche = i
                    }
                }
                saisie = proche
                invalidate()
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = ev.rawX - x0
                val dy = ev.rawY - y0
                x0 = ev.rawX; y0 = ev.rawY
                if (saisie < 0) {
                    for (p in points) p.offset(dx, dy)
                } else {
                    points[saisie].offset(dx, dy)
                    if (estNoire(saisie)) {
                        // Régler une noire règle le retrait de toutes les noires : elles sont dessinées pareil.
                        retraitNoires = PointF(
                            points[saisie].x - (points[saisie - 1].x + points[saisie + 1].x) / 2,
                            points[saisie].y - (points[saisie - 1].y + points[saisie + 1].y) / 2,
                        )
                        disposition.groupes.forEach(::placerNoires)
                    } else {
                        disposition.groupes.firstOrNull { saisie == it.first || saisie == it.last }?.let(::repartir)
                    }
                }
                invalidate()
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                // Une pastille sortie de l'écran ne pourrait plus être rattrapée.
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
        for (rangee in disposition.groupes) {
            val a = points[rangee.first]
            val b = points[rangee.last]
            canvas.drawLine(a.x - ox, a.y - oy, b.x - ox, b.y - oy, ligne)
        }
        points.forEachIndexed { i, p ->
            val x = p.x - ox
            val y = p.y - oy
            val bout = estBout(i)
            val rayon = (if (bout) 15 else 12) * dp
            if (i == saisie) {
                // Le doigt cache la pastille : une croix qui dépasse montre où elle vise.
                canvas.drawLine(x - 46 * dp, y, x + 46 * dp, y, croix)
                canvas.drawLine(x, y - 46 * dp, x, y + 46 * dp, croix)
            }
            canvas.drawCircle(x, y, rayon, if (i == active) fondActif else if (bout) fondBout else fondMilieu)
            canvas.drawCircle(x, y, rayon, bord)
            canvas.drawText(noms[disposition.notes[i] % 12], x, y - (texte.ascent() + texte.descent()) / 2, texte)
        }
    }

    companion object {
        private val NOIRES = setOf(1, 3, 6, 8, 10)

        /** Grille de départ : rangées dans la moitié basse de l'écran, là où le jeu met ses touches. */
        fun grilleParDefaut(d: Disposition, largeur: Int, hauteur: Int, inverse: Boolean): List<PointF> {
            val points = List(d.notes.size) { PointF() }
            val n = d.groupes.size
            d.groupes.forEachIndexed { r, rangee ->
                val ligne = if (inverse) n - 1 - r else r
                val y = hauteur * (0.52f + 0.34f * (if (n > 1) ligne.toFloat() / (n - 1) else 0.5f))
                val combien = rangee.last - rangee.first
                for (i in rangee) {
                    val part = if (combien > 0) (i - rangee.first).toFloat() / combien else 0.5f
                    points[i].set(largeur * (0.2f + 0.6f * part), y)
                }
            }
            return points
        }
    }
}

/**
 * Calque du calibrage du dessin : quatre repères à poser sur l'outil de peinture du jeu.
 * Les deux premiers sont les coins de la toile (la zone rayée, pas son cadre), les deux suivants la
 * première et la dernière pastille de la palette. Mêmes coordonnées d'écran que [CalibrageView].
 */
class ReperesDessinView(context: Context, val points: List<PointF>, private val noms: Array<String>) : View(context) {
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
        // La toile.
        for (p in arrayOf(halo, trait)) {
            canvas.drawRect(points[0].x - ox, points[0].y - oy, points[1].x - ox, points[1].y - oy, p)
        }
        // Les 16 pastilles, réparties entre la première et la dernière.
        for (k in 0 until Dessin.PALETTE.size) {
            val c = Dessin.pastille(points[2], points[3], k)
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
            // L'étiquette se met du côté où il reste de la place.
            val gauche = if (x + 14 * dp + largeur > width) x - 14 * dp - largeur else x + 14 * dp
            canvas.drawRoundRect(gauche - 5 * dp, y - 11 * dp, gauche + largeur + 5 * dp, y + 9 * dp, 8 * dp, 8 * dp, etiquette)
            canvas.drawText(noms[i], gauche, y + 4 * dp, texte)
        }
    }
}

/**
 * Démonstration du calibrage sur l'écran de bienvenue : un petit instrument du jeu (trois rangées de
 * touches caramel), les pastilles qu'un doigt fait glisser sur la première et la dernière touche de
 * chaque rangée, puis quelques notes jouées. Purement décorative : elle ne reçoit aucun appui.
 * Animations coupées dans les réglages d'Android : on montre l'image fixe des pastilles en place.
 */
class DemoCalibrageView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    private val dp = resources.displayMetrics.density
    private var t = FIXE
    private var animation: ValueAnimator? = null

    private fun plein(couleur: Int) = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = context.getColor(couleur) }
    private fun trait(couleur: Int, epaisseur: Float) = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = epaisseur * dp; color = context.getColor(couleur)
    }

    private val fond = plein(R.color.c_jeu_fond)
    private val sol = plein(R.color.c_jeu_sol)
    private val touche = plein(R.color.c_caramel)
    private val toucheBord = trait(R.color.c_caramel_bord, 1.5f)
    private val toucheJouee = plein(R.color.c_menthe)
    private val bout = plein(R.color.c_primary)
    private val milieu = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xF2FFFAF1.toInt() }
    private val pastilleBord = trait(R.color.c_brand_edge, 1.5f)
    private val guide = trait(R.color.blanc, 1.5f).apply { alpha = 170 }
    private val bulle = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFFFFAF1.toInt() }
    private val bulleBord = trait(R.color.c_primary, 2.5f)
    private val doigt = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0x66FFFFFF }
    private val doigtBord = trait(R.color.blanc, 2f)
    private val cadre = RectF()

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (!ValueAnimator.areAnimatorsEnabled()) return
        animation = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = 7000
            interpolator = LinearInterpolator()
            repeatCount = ValueAnimator.INFINITE
            addUpdateListener {
                t = it.animatedValue as Float
                invalidate()
            }
            if (isShown) start()
        }
    }

    override fun onDetachedFromWindow() {
        animation?.cancel()
        animation = null
        super.onDetachedFromWindow()
    }

    /** Écran de bienvenue caché (on est sur l'accueil) : inutile de redessiner dans le vide. */
    override fun onVisibilityAggregated(isVisible: Boolean) {
        super.onVisibilityAggregated(isVisible)
        val a = animation ?: return
        if (isVisible && !a.isStarted) a.start() else if (!isVisible && a.isStarted) a.cancel()
    }

    /** 0 avant [debut], 1 après [fin], adouci entre les deux. */
    private fun part(debut: Float, fin: Float): Float {
        val x = ((t - debut) / (fin - debut)).coerceIn(0f, 1f)
        return x * x * (3 - 2 * x)
    }

    override fun onDraw(canvas: Canvas) {
        val l = width.toFloat()
        val h = height.toFloat()
        cadre.set(0f, 0f, l, h)
        canvas.drawRoundRect(cadre, 16 * dp, 16 * dp, fond)
        canvas.save()
        canvas.clipRect(0f, 0f, l, h - 8 * dp)
        canvas.drawOval(l * 0.06f, h * 0.22f, l * 0.94f, h * 1.4f, sol)
        canvas.restore()

        val rayon = minOf(h * 0.085f, l * 0.05f)
        // La bulle de DodoTopia, en haut à droite du « jeu ».
        canvas.drawCircle(l - 2.6f * rayon, 2.4f * rayon, 1.5f * rayon, bulle)
        canvas.drawCircle(l - 2.6f * rayon, 2.4f * rayon, 1.5f * rayon, bulleBord)

        val jouee = if (t >= DEBUT_JEU) MELODIE.getOrNull(((t - DEBUT_JEU) / PAS_JEU).toInt()) ?: -1 else -1
        var doigtX = 0f
        var doigtY = 0f
        var doigtVu = false
        // Les touches gardent l'écart du jeu : au plus quatre rayons d'une touche à la suivante.
        val demi = minOf(l * 0.28f, rayon * 4.2f * (PAR_RANGEE - 1) / 2)
        val gauche = l / 2 - demi
        val droite = l / 2 + demi
        for (r in 0 until RANGEES) {
            val y = h * (0.40f + 0.22f * r)
            // Chaque rangée à son tour, de celle du haut à celle du bas : la première pastille, puis la dernière.
            val debut = 0.06f + 0.2f * r
            val a = part(debut, debut + 0.08f)
            val b = part(debut + 0.09f, debut + 0.18f)
            val ax = gauche + demi * 0.5f * (1 - a)
            val bx = droite - demi * 0.6f * (1 - b)
            val ay = y - h * 0.11f * (1 - a)
            val by = y - h * 0.11f * (1 - b)
            for (k in 0 until PAR_RANGEE) {
                val x = gauche + (droite - gauche) * k / (PAR_RANGEE - 1)
                val active = jouee == r * PAR_RANGEE + k
                canvas.drawCircle(x, y, rayon * (if (active) 1.18f else 1f), if (active) toucheJouee else touche)
                canvas.drawCircle(x, y, rayon * (if (active) 1.18f else 1f), toucheBord)
            }
            canvas.drawLine(ax, ay, bx, by, guide)
            for (k in 0 until PAR_RANGEE) {
                val x = ax + (bx - ax) * k / (PAR_RANGEE - 1)
                val yy = ay + (by - ay) * k / (PAR_RANGEE - 1)
                val auBout = k == 0 || k == PAR_RANGEE - 1
                val rp = rayon * (if (auBout) 0.74f else 0.56f)
                canvas.drawCircle(x, yy, rp, if (auBout) bout else milieu)
                canvas.drawCircle(x, yy, rp, pastilleBord)
            }
            if (a > 0f && a < 1f) {
                doigtX = ax; doigtY = ay; doigtVu = true
            } else if (b > 0f && b < 1f) {
                doigtX = bx; doigtY = by; doigtVu = true
            }
        }
        if (doigtVu) {
            canvas.drawCircle(doigtX, doigtY, rayon * 1.7f, doigt)
            canvas.drawCircle(doigtX, doigtY, rayon * 1.7f, doigtBord)
        }
    }

    private companion object {
        const val RANGEES = 3
        const val PAR_RANGEE = 5

        /** Tout est en place : c'est aussi l'image fixe. */
        const val FIXE = 0.68f
        const val DEBUT_JEU = 0.70f
        const val PAS_JEU = 0.035f

        /** Indices de touches (rangée × 5 + colonne) : une petite montée qui redescend. */
        val MELODIE = intArrayOf(10, 11, 12, 6, 7, 8, 2, 7)
    }
}

/** Pictogramme d'un clavier : ses rangées de touches en points, dièses compris, pour le reconnaître d'un coup d'œil. */
class MiniClavierView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    private val dp = resources.displayMetrics.density
    private val blanche = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = context.getColor(R.color.c_ambre_encre) }
    private val noire = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = context.getColor(R.color.c_ambre_trait) }
    private var notes = IntArray(0)
    private var rangees = IntArray(0)

    fun montrer(d: Disposition) {
        notes = d.notes
        rangees = d.rangees
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        if (rangees.isEmpty()) return
        val marge = 7 * dp
        val l = width - 2 * marge
        val h = height - 2 * marge
        val pasX = l / rangees.max()
        val pasY = h / rangees.size
        val rayon = minOf(pasX, pasY) * 0.38f
        var i = 0
        rangees.forEachIndexed { r, combien ->
            // Rangée grave en bas, comme dans le jeu ; chaque rangée est centrée.
            val y = marge + pasY * (rangees.size - 1 - r + 0.5f)
            val x0 = marge + (l - pasX * combien) / 2 + pasX / 2
            for (k in 0 until combien) {
                val diese = notes[i] % 12 in DIESES
                canvas.drawCircle(x0 + pasX * k, y, rayon, if (diese) noire else blanche)
                i++
            }
        }
    }

    private companion object {
        val DIESES = setOf(1, 3, 6, 8, 10)
    }
}
