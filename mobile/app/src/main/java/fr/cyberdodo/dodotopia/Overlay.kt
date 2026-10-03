package fr.cyberdodo.dodotopia

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.PixelFormat
import android.graphics.PointF
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.ContextThemeWrapper
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewGroup
import android.view.WindowManager
import android.view.animation.AlphaAnimation
import android.view.animation.Animation
import android.view.animation.OvershootInterpolator
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.lifecycle.Observer
import java.io.IOException
import kotlin.math.hypot
import kotlin.math.min

/**
 * Tout ce que DodoTopia affiche par-dessus le jeu : la bulle, son menu (Musique, Outils), la carte
 * de lecture et le calibrage des touches. Ce sont des fenêtres TYPE_ACCESSIBILITY_OVERLAY, que seul
 * le WindowManager du service d'accessibilité a le droit de créer.
 *
 * Un geste envoyé par le service atterrit sur la fenêtre qui se trouve à cet endroit, les nôtres
 * comprises. D'où le menu replié pendant la lecture, la carte non tactile, le calibrage rendu
 * non tactile pendant son test et la bulle écartée des touches avant de jouer.
 */
class Overlay(private val service: DodoAccessibilityService) {

    private enum class Etat { FERME, OUVERT, LECTURE }
    private enum class Onglet { MUSIQUE, DESSIN, CUISINE, OUTILS, SALON }

    /** Ce qui envoie des gestes en ce moment. */
    private enum class Jeu { RIEN, MORCEAU, TEST_TOUCHES, LATENCE, SALON, DESSIN, CUISINE }

    private class Reprise(val id: String, val positionMs: Long)

    private val contexte: Context = ContextThemeWrapper(service, R.style.Theme_DodoOverlay)
    private val fenetres = service.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val gonfleur = LayoutInflater.from(contexte)
    private val prefs = Preferences.prefs(service)
    private val biblio = Bibliotheque(service)
    private val principal = Handler(Looper.getMainLooper())
    private val dp = service.resources.displayMetrics.density

    private var onglet = Onglet.MUSIQUE
    private var message = ""
    private var resumeOutils = ""
    private var reprise: Reprise? = null
    private var jeu = Jeu.RIEN
    private var dureeLecture = 0L

    /** Instant (uptimeMillis) du départ synchronisé d'un salon : avant lui, la carte affiche le compte à rebours. */
    private var departSalon = 0L

    /** Le salon a changé (joueur arrivé, morceau choisi…) : l'onglet Salon du menu se remet à jour. */
    private val suiviSalon = Observer<Int> {
        if (panneau != null && (onglet == Onglet.SALON || !Salon.actif)) reouvrirPanneau()
    }

    private var bulle: View? = null
    private var bulleParams: WindowManager.LayoutParams? = null
    private var aide: View? = null
    private var panneau: View? = null
    private var carte: View? = null
    private var calibrage: CalibrageView? = null
    private var reperes: ReperesDessinView? = null
    private var reperesNuances: ReperesNuancesView? = null
    private var barre: View? = null

    private fun px(valeurDp: Int): Int = (valeurDp * dp).toInt()

    private fun texte(id: Int, vararg valeurs: Any): String = contexte.getString(id, *valeurs)

    // ------------------------------------------------------------------ fenêtres

    private fun params(largeur: Int, hauteur: Int, drapeaux: Int = 0): WindowManager.LayoutParams =
        WindowManager.LayoutParams(
            largeur, hauteur,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            // NO_LIMITS + IN_SCREEN : x et y comptent depuis le coin de l'écran, encoches comprises.
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or drapeaux,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }

    private fun retirer(vue: View?) {
        if (vue == null) return
        try {
            fenetres.removeView(vue)
        } catch (e: IllegalArgumentException) {
            // Déjà retirée (service coupé pendant une animation) : rien à faire.
        }
    }

    /** Laisse passer (ou non) les appuis au travers d'une de nos fenêtres. */
    private fun tactile(vue: View?, oui: Boolean) {
        val p = vue?.layoutParams as? WindowManager.LayoutParams ?: return
        val drapeau = WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        p.flags = if (oui) p.flags and drapeau.inv() else p.flags or drapeau
        if (vue.isAttachedToWindow) fenetres.updateViewLayout(vue, p)
    }

    /**
     * Place une fenêtre à côté de la bulle : du côté libre, à 16 dp du cercle.
     * Si la largeur manque (téléphone en portrait), elle passe sous la bulle, ou au-dessus.
     */
    private fun placerPresDeLaBulle(p: WindowManager.LayoutParams, hautPrefere: Int?) {
        val b = bulleParams ?: return
        val ecran = tailleEcran(service)
        val marge = px(8)
        val aDroite = b.x + b.width / 2 > ecran.x / 2
        // La fenêtre de la bulle garde 10 dp de marge autour du cercle : 16 dp d'écart visible = 6 dp entre fenêtres.
        val x = if (aDroite) b.x - px(6) - p.width else b.x + b.width + px(6)
        if (x >= marge && x + p.width <= ecran.x - marge) {
            p.x = x
            p.y = (hautPrefere ?: (b.y + b.height / 2 - p.height / 2))
                .coerceIn(marge, (ecran.y - p.height - marge).coerceAtLeast(marge))
        } else {
            p.x = (ecran.x - p.width) / 2
            val dessous = b.y + b.height
            p.y = when {
                hautPrefere != null -> hautPrefere + px(24)
                dessous + p.height <= ecran.y - marge -> dessous
                b.y - p.height >= marge -> b.y - p.height
                else -> (ecran.y - p.height) / 2
            }
        }
    }

    /** Déplace une fenêtre au doigt. Sans glissement, c'est un clic. */
    private inner class Glisser(
        private val p: WindowManager.LayoutParams,
        private val seuil: Int,
        private val surClic: () -> Unit,
        private val surLacher: () -> Unit,
    ) : View.OnTouchListener {
        private var x0 = 0f
        private var y0 = 0f
        private var px = 0
        private var py = 0
        private var glisse = false
        private var avale = false

        @SuppressLint("ClickableViewAccessibility")
        override fun onTouch(v: View, ev: MotionEvent): Boolean {
            if (avale && ev.actionMasked != MotionEvent.ACTION_DOWN) return true
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    x0 = ev.rawX; y0 = ev.rawY; px = p.x; py = p.y; glisse = false
                    // Pendant qu'on joue ou qu'on peint, le premier contact arrête tout de suite : les gestes
                    // envoyés au jeu se mêlent à ce toucher et le feraient passer pour un déplacement de la bulle.
                    avale = jeu != Jeu.RIEN
                    if (avale) surClic() else v.animate().scaleX(0.9f).scaleY(0.9f).setDuration(90).start()
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = ev.rawX - x0
                    val dy = ev.rawY - y0
                    if (!glisse && hypot(dx, dy) > seuil) glisse = true
                    if (glisse && v.isAttachedToWindow) {
                        p.x = px + dx.toInt(); p.y = py + dy.toInt()
                        fenetres.updateViewLayout(v, p)
                    }
                }
                MotionEvent.ACTION_UP -> {
                    v.animate().scaleX(1f).scaleY(1f).setDuration(160).setInterpolator(OvershootInterpolator(3f)).start()
                    if (glisse) surLacher() else surClic()
                }
                MotionEvent.ACTION_CANCEL -> {
                    v.animate().scaleX(1f).scaleY(1f).setDuration(120).start()
                    if (glisse) surLacher()
                }
            }
            return true
        }
    }

    /** Retire tout, bulle comprise : service coupé, ou bulle éteinte depuis l'appli. */
    fun fermerTout() {
        arreterGestes()
        principal.removeCallbacksAndMessages(null)
        Salon.changement.removeObserver(suiviSalon)
        fermerCalibrage()
        fermerReperes()
        fermerPanneau()
        fermerCarte()
        fermerAide()
        retirer(bulle)
        bulle = null
        bulleParams = null
    }

    /** Les positions n'ont plus de sens après une rotation : on arrête, on replie tout et on range la bulle. */
    fun surRotation() {
        if (bulle == null) return
        arreterGestes()
        fermerCalibrage()
        fermerReperes()
        fermerPanneau()
        fermerCarte()
        fermerAide()
        etatBulle(Etat.FERME)
        principal.post { rangerBulle(anime = false) }
    }

    // ------------------------------------------------------------------ bulle

    fun montrerBulle() {
        if (bulle != null) return
        val vue = gonfleur.inflate(R.layout.overlay_bulle, null)
        vue.findViewById<View>(R.id.imgBulle).clipToOutline = true
        val taille = px(TAILLE_BULLE_DP)
        val ecran = tailleEcran(service)
        // En paysage (le jeu) : en haut, loin des touches de l'instrument. En portrait (l'appli) : sous ses réglages.
        val hauteur = if (ecran.x > ecran.y) ecran.y / 4 else ecran.y * 3 / 5
        val p = params(taille, taille).apply { x = ecran.x - taille; y = hauteur - taille / 2 }
        vue.setOnTouchListener(
            Glisser(p, ViewConfiguration.get(contexte).scaledTouchSlop, ::clicBulle) { rangerBulle(anime = true) }
        )
        fenetres.addView(vue, p)
        vue.scaleX = 0f
        vue.scaleY = 0f
        vue.animate().scaleX(1f).scaleY(1f).setDuration(260).setInterpolator(OvershootInterpolator(2f)).start()
        bulle = vue
        bulleParams = p
        etatBulle(Etat.FERME)
        montrerAide()
        Salon.changement.observeForever(suiviSalon)
    }

    private fun clicBulle() {
        fermerAide()
        when {
            jeu != Jeu.RIEN -> arretUrgence()
            calibrage != null -> {
                fermerCalibrage()
                ouvrirPanneau()
            }
            reperes != null || reperesNuances != null -> {
                fermerReperes()
                ouvrirPanneau()
            }
            panneau != null -> {
                fermerPanneau()
                etatBulle(Etat.FERME)
            }
            else -> ouvrirPanneau()
        }
    }

    /** Colle la bulle au bord gauche ou droit le plus proche, sans la laisser sortir en hauteur. */
    private fun rangerBulle(anime: Boolean) {
        val vue = bulle ?: return
        val p = bulleParams ?: return
        fermerAide()
        val ecran = tailleEcran(service)
        val taille = p.width
        val cible = if (p.x + taille / 2 < ecran.x / 2) 0 else ecran.x - taille
        p.y = p.y.coerceIn(0, ecran.y - taille)
        // Le menu suit la bulle : on le repose à côté de sa nouvelle place.
        val replacer = { if (panneau != null) reouvrirPanneau() }
        if (!anime) {
            p.x = cible
            if (vue.isAttachedToWindow) fenetres.updateViewLayout(vue, p)
            replacer()
            return
        }
        ValueAnimator.ofInt(p.x, cible).apply {
            duration = 180
            addUpdateListener {
                p.x = it.animatedValue as Int
                if (vue.isAttachedToWindow) fenetres.updateViewLayout(vue, p)
            }
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) = replacer()
            })
            start()
        }
    }

    /**
     * La bulle avale les appuis qui tombent dessus : avant de jouer, si elle recouvre une touche,
     * on la glisse le long des bords jusqu'à une place libre.
     */
    private fun ecarterBulle(touches: List<PointF>) {
        val vue = bulle ?: return
        val p = bulleParams ?: return
        val taille = p.width
        fun gene(x: Int, y: Int) = touches.any { it.x >= x && it.x <= x + taille && it.y >= y && it.y <= y + taille }
        if (!gene(p.x, p.y)) return
        val ecran = tailleEcran(service)
        val bords = if (p.x == 0) intArrayOf(0, ecran.x - taille) else intArrayOf(ecran.x - taille, 0)
        for (x in bords) {
            var y = 0
            while (y <= ecran.y - taille) {
                if (!gene(x, y)) {
                    p.x = x; p.y = y
                    if (vue.isAttachedToWindow) fenetres.updateViewLayout(vue, p)
                    return
                }
                y += taille / 2
            }
        }
    }

    /** Les trois visages de la bulle : fermée (pastille verte), menu ouvert (croix), en lecture (anneau ambre, pause). */
    private fun etatBulle(etat: Etat) {
        val vue = bulle ?: return
        val badge = vue.findViewById<ImageView>(R.id.badge)
        vue.findViewById<View>(R.id.cercle).setBackgroundResource(
            if (etat == Etat.LECTURE) R.drawable.bulle_fond_actif else R.drawable.bulle_fond
        )
        vue.findViewById<View>(R.id.imgBulle).alpha = if (etat == Etat.FERME) 1f else 0.4f
        vue.findViewById<View>(R.id.pastille).visibility = visible(etat == Etat.FERME)
        vue.findViewById<View>(R.id.anneau).apply {
            visibility = visible(etat == Etat.LECTURE)
            // L'anneau respire tant que DodoTopia joue, peint ou cuisine.
            if (etat == Etat.LECTURE) {
                startAnimation(AlphaAnimation(1f, 0.3f).apply { duration = 750; repeatMode = Animation.REVERSE; repeatCount = Animation.INFINITE })
            } else {
                clearAnimation()
            }
        }
        badge.visibility = visible(etat != Etat.FERME)
        if (etat == Etat.LECTURE) {
            badge.setBackgroundResource(R.drawable.rond_ambre)
            badge.setImageResource(R.drawable.ic_pause)
            badge.imageTintList = ColorStateList.valueOf(contexte.getColor(R.color.blanc))
        } else {
            badge.setBackgroundResource(R.drawable.rond_sombre)
            badge.setImageResource(R.drawable.ic_fermer)
            badge.imageTintList = ColorStateList.valueOf(contexte.getColor(R.color.c_caramel_ink))
        }
    }

    /** « Appuie pour ouvrir DodoTopia » : quelques secondes à l'apparition de la bulle, sans gêner le jeu. */
    private fun montrerAide() {
        val b = bulleParams ?: return
        val vue = gonfleur.inflate(R.layout.overlay_aide, null)
        vue.measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED)
        val p = params(vue.measuredWidth, vue.measuredHeight, WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE).apply {
            x = if (b.x > 0) b.x - vue.measuredWidth else b.x + b.width
            y = b.y + (b.height - vue.measuredHeight) / 2
        }
        fenetres.addView(vue, p)
        vue.alpha = 0f
        vue.animate().alpha(1f).setStartDelay(250).setDuration(200).start()
        aide = vue
        principal.postDelayed(::fermerAide, 4500)
    }

    private fun fermerAide() {
        retirer(aide)
        aide = null
    }

    // ------------------------------------------------------------------ menu

    private fun ouvrirPanneau(apparition: Boolean = true) {
        if (panneau != null || bulle == null) return
        val vue = gonfleur.inflate(R.layout.overlay_panneau, null)
        val ecran = tailleEcran(service)

        if (onglet == Onglet.SALON && !Salon.actif) onglet = Onglet.MUSIQUE
        onglet(vue, R.id.ongletMusique, R.drawable.ic_note, Onglet.MUSIQUE)
        onglet(vue, R.id.ongletSalon, R.drawable.ic_groupe, Onglet.SALON)
        vue.findViewById<View>(R.id.ongletSalon).visibility = visible(Salon.actif)
        vue.findViewById<View>(R.id.pageSalon).visibility = visible(onglet == Onglet.SALON)
        onglet(vue, R.id.ongletDessin, R.drawable.ic_pinceau, Onglet.DESSIN)
        onglet(vue, R.id.ongletCuisine, R.drawable.ic_marmite, Onglet.CUISINE)
        onglet(vue, R.id.ongletOutils, R.drawable.ic_reglages, Onglet.OUTILS)
        vue.findViewById<View>(R.id.pageCuisine).visibility = visible(onglet == Onglet.CUISINE)
        vue.findViewById<View>(R.id.pageDessin).visibility = visible(onglet == Onglet.DESSIN)
        vue.findViewById<View>(R.id.pageMusique).visibility = visible(onglet == Onglet.MUSIQUE)
        vue.findViewById<View>(R.id.pageOutils).visibility = visible(onglet == Onglet.OUTILS)
        vue.findViewById<View>(R.id.lienOuvrir).setOnClickListener {
            fermerPanneau()
            etatBulle(Etat.FERME)
            service.startActivity(
                Intent(service, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        }
        when (onglet) {
            Onglet.MUSIQUE -> remplirMusique(vue, ecran.y)
            Onglet.DESSIN -> remplirDessin(vue)
            Onglet.CUISINE -> remplirCuisine(vue)
            Onglet.OUTILS -> remplirOutils(vue)
            Onglet.SALON -> remplirSalon(vue)
        }

        // Largeur fixe, hauteur du contenu plafonnée à l'écran.
        val largeur = min(px(LARGEUR_MENU_DP), ecran.x - px(16))
        vue.measure(
            View.MeasureSpec.makeMeasureSpec(largeur, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(ecran.y - px(16), View.MeasureSpec.AT_MOST)
        )
        val p = params(largeur, vue.measuredHeight)
        placerPresDeLaBulle(p, null)
        fenetres.addView(vue, p)
        if (apparition) {
            // Le menu sort de la bulle : il grandit depuis le côté où elle se trouve.
            vue.pivotX = if ((bulleParams?.x ?: 0) > p.x) p.width.toFloat() else 0f
            vue.pivotY = p.height / 2f
            vue.alpha = 0f
            vue.scaleX = 0.9f
            vue.scaleY = 0.9f
            vue.animate().alpha(1f).scaleX(1f).scaleY(1f).setDuration(180).setInterpolator(OvershootInterpolator(1.2f)).start()
        } else {
            vue.alpha = 0.5f
            vue.animate().alpha(1f).setDuration(140).start()
        }
        panneau = vue
        etatBulle(Etat.OUVERT)
    }

    private fun fermerPanneau() {
        retirer(panneau)
        panneau = null
    }

    /** Le menu a une hauteur figée à l'ouverture : on le rouvre quand son contenu ou la place de la bulle change. */
    private fun reouvrirPanneau() {
        val ouvert = panneau != null
        fermerPanneau()
        ouvrirPanneau(apparition = !ouvert)
    }

    private fun visible(oui: Boolean) = if (oui) View.VISIBLE else View.GONE

    private fun onglet(vue: View, id: Int, icone: Int, cible: Onglet) {
        vue.findViewById<TextView>(id).apply {
            isSelected = onglet == cible
            if (onglet != cible) text = ""
            (layoutParams as LinearLayout.LayoutParams).weight = if (onglet == cible) 2.4f else 1f
            // Icône de 15 dp à gauche du libellé, de la couleur du texte.
            val dessin = contexte.getDrawable(icone)!!.mutate()
            dessin.setBounds(0, 0, px(15), px(15))
            dessin.setTint(currentTextColor)
            setCompoundDrawables(dessin, null, null, null)
            // Onglet replié : l'icône seule, sans l'écart prévu pour un libellé.
            compoundDrawablePadding = if (text.isEmpty()) 0 else px(5)
            val contenu = paint.measureText(text.toString()).toInt() + px(15) + compoundDrawablePadding
            // Centre le couple icône + texte dans la pilule (un TextView colle sinon l'icône au bord).
            // La largeur n'est connue qu'une fois la fenêtre posée : on attend la mise en page.
            addOnLayoutChangeListener { _, gauche, _, droite, _, _, _, _, _ ->
                val marge = ((droite - gauche - contenu) / 2).coerceAtLeast(0)
                if (paddingLeft != marge) post { setPadding(marge, 0, 0, 0) }
            }
            gravity = Gravity.CENTER_VERTICAL
            setOnClickListener {
                if (onglet != cible) {
                    onglet = cible
                    reouvrirPanneau()
                }
            }
        }
    }

    private fun remplirMusique(vue: View, hauteurEcran: Int) {
        val d = Preferences.disposition(service)
        val calibre = Preferences.touches(service, d) != null
        val choisi = biblio.choisi()
        val pause = reprise?.takeIf { it.id == choisi.id }

        vue.findViewById<TextView>(R.id.alerte).apply {
            visibility = visible(!calibre)
            setOnClickListener { ouvrirCalibrage() }
        }

        val liste = vue.findViewById<ViewGroup>(R.id.listeMorceaux)
        val morceaux = biblio.liste()
        for (m in morceaux) {
            val ligne = gonfleur.inflate(R.layout.item_morceau_bulle, liste, false)
            ligne.isSelected = m.id == choisi.id
            ligne.findViewById<TextView>(R.id.titre).text = m.titre
            ligne.findViewById<TextView>(R.id.duree).text = minutes(m.dureeMs)
            ligne.setOnClickListener {
                if (m.id != choisi.id) {
                    biblio.choisir(m.id)
                    message = ""
                    reouvrirPanneau()
                }
            }
            liste.addView(ligne)
        }
        // La liste défile dans ce qui reste de hauteur une fois le reste du menu posé.
        val reste = hauteurEcran - px(if (calibre) 190 else 250)
        vue.findViewById<View>(R.id.defilMorceaux).apply {
            layoutParams.height = min(morceaux.size * px(HAUTEUR_LIGNE_DP), reste.coerceAtLeast(px(HAUTEUR_LIGNE_DP * 2)))
            val rang = morceaux.indexOfFirst { it.id == choisi.id }
            post { scrollTo(0, (rang - 1).coerceAtLeast(0) * px(HAUTEUR_LIGNE_DP)) }
        }

        pas(vue, R.id.vitesseMoins, R.id.vitesseValeur, R.id.vitessePlus, VITESSE, 100, 50, 150, 10) { "$it %" }
        vue.findViewById<View>(R.id.btnDebut).apply {
            visibility = visible(pause != null)
            setOnClickListener {
                reprise = null
                lancerLecture(0)
            }
        }
        vue.findViewById<View>(R.id.btnLancer).setOnClickListener { lancerLecture(pause?.positionMs ?: 0) }
        vue.findViewById<TextView>(R.id.txtInfo).text = when {
            message.isNotEmpty() -> message
            pause != null -> texte(R.string.info_pause, minutes(pause.positionMs), minutes(choisi.dureeMs))
            else -> texte(R.string.info_clavier, texte(d.nom))
        }
    }

    private fun remplirOutils(vue: View) {
        val d = Preferences.disposition(service)
        val calibre = Preferences.touches(service, d) != null
        vue.findViewById<TextView>(R.id.txtClavier).text =
            texte(if (calibre) R.string.clavier_calibre else R.string.clavier_a_calibrer, texte(d.nom))
        vue.findViewById<TextView>(R.id.btnCalibrer).apply {
            setText(if (calibre) R.string.calibrer_encore else R.string.calibrer)
            setOnClickListener { ouvrirCalibrage() }
        }
        pas(vue, R.id.appuiMoins, R.id.appuiValeur, R.id.appuiPlus, APPUI, APPUI_DEFAUT, 20, 200, 10) { "$it ms" }
        vue.findViewById<View>(R.id.btnLatence).setOnClickListener { lancerLatence() }
        vue.findViewById<View>(R.id.btnCapture).setOnClickListener { capturer() }
        vue.findViewById<TextView>(R.id.txtResume).apply {
            text = resumeOutils
            visibility = visible(resumeOutils.isNotEmpty())
        }
    }

    private fun remplirDessin(vue: View) {
        val t = Dessin.charger(service)
        val calibre = t != null && Preferences.reperesDessin(service, t.format) != null
        // Sans capture d'écran (Android 10), ni nuances ni pot : impossible de lire la page affichée ou de voir une fuite.
        val voit = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R
        val nuancesReperees = Preferences.reperesNuances(service) != null
        val outilsReperes = Preferences.reperesOutils(service) != null
        val avecNuances = voit && nuancesReperees && Preferences.nuancesVoulues(service)
        val avecPot = voit && outilsReperes && Preferences.potVoulu(service)
        val pause = t?.let { Peintre.reprise(service, Peintre.cle(it, avecNuances)) }
        vue.findViewById<TextView>(R.id.dessinEtat).text = when {
            t == null -> texte(R.string.dessin_sans_image)
            message.isNotEmpty() -> message
            pause != null -> texte(R.string.dessin_pause, pause)
            !calibre -> texte(R.string.dessin_a_calibrer, t.format)
            else -> texte(R.string.dessin_pret, t.format, t.largeur, t.hauteur, t.couleurs(avecNuances))
        }
        vue.findViewById<TextView>(R.id.dessinCalibrer).apply {
            // Sans image choisie dans l'appli : un dessin d'exemple, pour essayer sans quitter le jeu.
            setText(if (t == null) R.string.dessin_exemple else if (calibre) R.string.dessin_recalibrer else R.string.dessin_calibrer)
            setOnClickListener {
                if (t != null) {
                    ouvrirReperes(t)
                } else {
                    val image = android.graphics.BitmapFactory.decodeResource(service.resources, R.drawable.dodo)
                    Dessin.enregistrer(service, Dessin.convertir(image, Dessin.FORMATS[0]))
                    image.recycle()
                    reouvrirPanneau()
                }
            }
        }
        vue.findViewById<View>(R.id.dessinReperer).setOnClickListener { ouvrirReperesNuances(Pour.RIEN) }
        // Les 16 couleurs et le crayon seul restent le choix de départ : nuances et pot s'allument une fois repérés.
        interrupteur(vue, R.id.dessinNuances, avecNuances) {
            when {
                !voit -> message = texte(R.string.dessin_android11)
                !nuancesReperees -> {
                    ouvrirReperesNuances(Pour.NUANCES)
                    return@interrupteur
                }
                else -> {
                    Preferences.definirNuancesVoulues(service, !avecNuances)
                    message = ""
                }
            }
            reouvrirPanneau()
        }
        interrupteur(vue, R.id.dessinPot, avecPot) {
            when {
                !voit -> message = texte(R.string.dessin_android11)
                !outilsReperes -> {
                    ouvrirReperesNuances(Pour.POT)
                    return@interrupteur
                }
                else -> {
                    Preferences.definirPotVoulu(service, !avecPot)
                    message = ""
                }
            }
            reouvrirPanneau()
        }
        pas(vue, R.id.dessinMoins, R.id.dessinValeur, R.id.dessinPlus, CASE_MS, CASE_MS_DEFAUT, 8, 40, 2) { "$it ms" }
        vue.findViewById<View>(R.id.dessinDebut).apply {
            visibility = visible(pause != null)
            setOnClickListener {
                Peintre.oublierReprise(service)
                lancerDessin(reprendre = false)
            }
        }
        vue.findViewById<View>(R.id.dessinLancer).apply {
            isEnabled = t != null
            alpha = if (t != null) 1f else 0.4f
            setOnClickListener { lancerDessin(reprendre = true) }
        }
    }

    /** Un interrupteur du menu : allumé ou non, et ce qu'un appui déclenche. */
    private fun interrupteur(vue: View, id: Int, allume: Boolean, surClic: () -> Unit) {
        vue.findViewById<View>(id).apply {
            isSelected = allume
            setOnClickListener { surClic() }
        }
    }

    private fun remplirCuisine(vue: View) {
        val cuisine = service.cuisine
        vue.findViewById<TextView>(R.id.cuisineEtat).text = when {
            cuisine == null -> texte(R.string.cuisine_android11)
            message.isNotEmpty() && cuisine.plats > 0 -> message + "\n" + texte(R.string.cuisine_bilan, cuisine.plats, cuisine.feux)
            message.isNotEmpty() -> message
            cuisine.plats > 0 || cuisine.feux > 0 -> texte(R.string.cuisine_bilan, cuisine.plats, cuisine.feux)
            else -> texte(R.string.cuisine_aide)
        }
        vue.findViewById<View>(R.id.cuisineLancer).apply {
            isEnabled = cuisine != null
            alpha = if (cuisine != null) 1f else 0.4f
            setOnClickListener { lancerCuisine() }
        }
        interrupteur(vue, R.id.cuisinePlusieurs, Preferences.plusieursCuisinieres(service)) {
            Preferences.definirPlusieursCuisinieres(service, !Preferences.plusieursCuisinieres(service))
            reouvrirPanneau()
        }
    }

    /** Cuisine en boucle jusqu'à l'arrêt (bulle, volume bas) ou jusqu'à ce que le bouton Cuisiner ne lance plus rien. */
    private fun lancerCuisine() {
        val cuisine = service.cuisine ?: return
        if (jeu != Jeu.RIEN) return
        message = ""
        fermerPanneau()
        val plusieurs = Preferences.plusieursCuisinieres(service)
        // La bulle doit rester hors de la zone où la cuisine cherche celles des cuisinières : son logo a du blanc.
        val ecran = tailleEcran(service)
        val z = CuisineVue.zone(plusieurs)
        val zone = ArrayList<PointF>()
        for (i in 0..10) for (j in 0..10) {
            zone.add(PointF(ecran.x * (z[0] + (z[1] - z[0]) * i / 10), ecran.y * (z[2] + (z[3] - z[2]) * j / 10)))
        }
        ecarterBulle(zone)
        etatBulle(Etat.LECTURE)
        jeu = Jeu.CUISINE
        cuisine.demarrer(plusieurs) { raison ->
            jeu = Jeu.RIEN
            message = texte(raison)
            onglet = Onglet.CUISINE
            reouvrirPanneau()
        }
    }

    private fun remplirSalon(vue: View) {
        val prets = Salon.joueurs.count { it.pret }
        vue.findViewById<TextView>(R.id.salonTitre).text =
            texte(R.string.salon_bulle_titre, Salon.code.orEmpty(), Salon.joueurs.size)
        vue.findViewById<TextView>(R.id.salonEtat).text = when {
            Salon.message.isNotEmpty() -> Salon.message
            Salon.morceau == null -> texte(R.string.salon_sans_morceau)
            Salon.telechargement -> texte(R.string.salon_telechargement, Salon.morceau!!.nom)
            else -> texte(R.string.salon_bulle_etat, Salon.morceau!!.nom, prets, Salon.joueurs.size)
        }
        vue.findViewById<TextView>(R.id.salonPret).apply {
            setText(if (Salon.pret) R.string.salon_plus_pret else R.string.salon_pret)
            isEnabled = Salon.etat == "lobby"
            setOnClickListener { Salon.basculerPret() }
        }
        vue.findViewById<TextView>(R.id.salonLancer).apply {
            visibility = visible(Salon.hote)
            setText(if (Salon.etat == "lobby") R.string.salon_lancer else R.string.salon_arreter)
            isEnabled = Salon.etat != "lobby" || Salon.morceau != null
            setOnClickListener { if (Salon.etat == "lobby") Salon.lancer() else Salon.arreter() }
        }
        // Arrivé pendant que les autres jouent : on peut prendre le morceau en marche.
        vue.findViewById<TextView>(R.id.salonRejoindreLecture).apply {
            visibility = visible(Salon.attenteRejoindre || Salon.positionARejoindre() != null)
            setText(if (Salon.attenteRejoindre) R.string.salon_rejoindre_annuler else R.string.salon_rejoindre_lecture)
            setOnClickListener {
                if (Salon.attenteRejoindre) Salon.annulerRejoindre() else Salon.rejoindreLecture(1500)
                reouvrirPanneau()
            }
        }
    }

    /** Lie un réglage « − valeur + » à sa préférence. */
    private fun pas(
        vue: View, idMoins: Int, idValeur: Int, idPlus: Int,
        cle: String, defaut: Int, mini: Int, maxi: Int, saut: Int, libelle: (Int) -> String,
    ) {
        val valeur = vue.findViewById<TextView>(idValeur)
        valeur.text = libelle(prefs.getInt(cle, defaut))
        fun changer(sens: Int) {
            val v = (prefs.getInt(cle, defaut) + sens * saut).coerceIn(mini, maxi)
            prefs.edit().putInt(cle, v).apply()
            valeur.text = libelle(v)
        }
        vue.findViewById<View>(idMoins).setOnClickListener { changer(-1) }
        vue.findViewById<View>(idPlus).setOnClickListener { changer(1) }
    }

    // ------------------------------------------------------------------ lecture

    private fun lancerLecture(depuisMs: Long) {
        if (jeu != Jeu.RIEN) return
        val d = Preferences.disposition(service)
        val touches = Preferences.touches(service, d)
        if (touches == null) {
            ouvrirCalibrage()
            return
        }
        val morceau = biblio.choisi()
        val arrangement = try {
            Arrangeur.arranger(biblio.notes(morceau.id), d)
        } catch (e: IOException) {
            null
        } catch (e: MidiIllisible) {
            null
        }
        if (arrangement == null || arrangement.frappes.isEmpty()) {
            message = texte(R.string.erreur_morceau)
            reouvrirPanneau()
            return
        }
        val vitesse = prefs.getInt(VITESSE, 100)
        message = ""
        reprise = null
        fermerPanneau()
        ecarterBulle(touches)
        etatBulle(Etat.LECTURE)
        dureeLecture = arrangement.dureeMs
        ouvrirCarte(
            texte(R.string.carte_role, texte(d.nom), vitesse),
            morceau.titre,
            texte(R.string.carte_pause),
        )
        jeu = Jeu.MORCEAU
        SpikeLog.log(
            "Lecture « ${morceau.titre} » · clavier ${d.id} · ${arrangement.frappes.size} frappes · " +
                "couverture ${arrangement.couverture} % · depuis ${depuisMs} ms"
        )
        service.lecteur.jouer(
            arrangement.frappes, touches, vitesse / 100f, depuisMs,
            prefs.getInt(APPUI, APPUI_DEFAUT).toLong(), DELAI_DEPART_MS,
        ) {
            if (jeu == Jeu.MORCEAU) {
                jeu = Jeu.RIEN
                fermerCarte()
                etatBulle(Etat.FERME)
            }
        }
        principal.post(battement)
    }

    /** Volume bas ou appui sur la bulle : met le morceau en pause, ou arrête le test en cours. */
    fun arretUrgence() {
        when (jeu) {
            Jeu.MORCEAU -> {
                val morceau = biblio.choisi()
                val position = service.lecteur.arreter()
                // Reprise un peu avant l'arrêt, pour retrouver le fil du morceau.
                reprise = Reprise(morceau.id, (position - RECUL_REPRISE_MS).coerceAtLeast(0))
                jeu = Jeu.RIEN
                fermerCarte()
                onglet = Onglet.MUSIQUE
                reouvrirPanneau()
            }
            Jeu.TEST_TOUCHES -> {
                service.lecteur.arreter()
                finTestTouches()
            }
            Jeu.LATENCE -> service.metronome.arreter(::finLatence)
            Jeu.SALON -> {
                // Je m'arrête seul : les autres continuent, le salon est prévenu.
                service.lecteur.arreter()
                jeu = Jeu.RIEN
                fermerCarte()
                Salon.finLecture(false)
                onglet = Onglet.SALON
                reouvrirPanneau()
            }
            Jeu.DESSIN -> {
                // Pause : les cases déjà peintes sont écrites sur le disque, le dessin reprendra où il en est.
                service.peintre.arreter()
                message = ""
                jeu = Jeu.RIEN
                fermerCarte()
                onglet = Onglet.DESSIN
                reouvrirPanneau()
            }
            Jeu.CUISINE -> {
                service.cuisine?.arreter()
                jeu = Jeu.RIEN
                message = ""
                onglet = Onglet.CUISINE
                reouvrirPanneau()
            }
            Jeu.RIEN -> Unit
        }
    }

    /** Coupe ce qui joue sans rien rouvrir (rotation, bulle éteinte). */
    private fun arreterGestes() {
        if (service.lecteur.enCours) service.lecteur.arreter()
        if (service.metronome.enCours) service.metronome.arreter { }
        service.cuisine?.arreter()
        service.peintre.arreter()
        principal.removeCallbacks(battement)
        val salon = jeu == Jeu.SALON
        jeu = Jeu.RIEN
        if (salon) Salon.finLecture(false)
    }

    // ------------------------------------------------------------------ dessin

    /** Pose les quatre repères du dessin sur l'outil de peinture du jeu. */
    private fun ouvrirReperes(t: Dessin.Travail) {
        fermerPanneau()
        if (reperes != null || reperesNuances != null || bulle == null) return
        val ecran = tailleEcran(service)
        // Départ : là où le jeu pose sa toile et sa palette (relevé sur un écran 16:9) ; il reste à ajuster au pixel.
        val hauteur = ecran.y * 0.61f
        val largeur = (hauteur * t.largeur / t.hauteur).coerceAtMost(ecran.x * 0.59f)
        val points = Preferences.reperesDessin(service, t.format) ?: listOf(
            PointF(ecran.x * 0.4894f - largeur / 2, ecran.y * 0.231f), PointF(ecran.x * 0.4894f + largeur / 2, ecran.y * 0.231f + hauteur),
            PointF(ecran.x * 0.899f, ecran.y * 0.24f), PointF(ecran.x * 0.963f, ecran.y * 0.8f),
        )
        val vue = ReperesDessinView(contexte, points, contexte.resources.getStringArray(R.array.reperes_dessin))
        fenetres.addView(vue, params(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT))
        reperes = vue

        val commandes = gonfleur.inflate(R.layout.overlay_reperes, null)
        commandes.findViewById<View>(R.id.btnAnnuler).setOnClickListener {
            fermerReperes()
            ouvrirPanneau()
        }
        commandes.findViewById<View>(R.id.btnOk).setOnClickListener {
            // Coins remis dans l'ordre haut-gauche, bas-droite, quel que soit le sens où ils ont été posés.
            val a = vue.points[0]
            val b = vue.points[1]
            val ranges = listOf(
                PointF(minOf(a.x, b.x), minOf(a.y, b.y)), PointF(maxOf(a.x, b.x), maxOf(a.y, b.y)), vue.points[2], vue.points[3],
            )
            Preferences.definirReperesDessin(service, t.format, ranges)
            SpikeLog.log("Repères du dessin ${t.format} · écran ${ecran.x}×${ecran.y} · " + ranges.joinToString(" ") { "(${it.x.toInt()},${it.y.toInt()})" })
            fermerReperes()
            message = ""
            onglet = Onglet.DESSIN
            ouvrirPanneau()
        }
        commandes.measure(
            View.MeasureSpec.makeMeasureSpec(ecran.x - px(16), View.MeasureSpec.AT_MOST),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        )
        val q = params(commandes.measuredWidth, WindowManager.LayoutParams.WRAP_CONTENT).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = px(10)
        }
        fenetres.addView(commandes, q)
        barre = commandes
        etatBulle(Etat.OUVERT)
    }

    /** Ce qui a demandé les repères des nuances et des outils : une fois validés, on allume ce que l'utilisateur voulait. */
    private enum class Pour { RIEN, NUANCES, POT }

    /**
     * Pose les repères des nuances (bouton palette, retour, flèches, première et dixième nuance) et des outils
     * (crayon, pot, Annuler). L'utilisateur doit avoir ouvert la page des nuances dans le jeu avant.
     */
    private fun ouvrirReperesNuances(pour: Pour) {
        fermerPanneau()
        if (reperes != null || reperesNuances != null || bulle == null) return
        val ecran = tailleEcran(service)
        // Départ : positions relevées sur PC (calibrage en 1920×1080, même disposition que sur mobile), ramenées à
        // la hauteur de cet écran ; la palette tient au bord droit, les outils au bord gauche. Aucune capture
        // de la page des nuances sur mobile : à ajuster à l'œil.
        val e = ecran.y / 900f
        fun aDroite(x: Int, y: Int) = PointF(ecran.x - (1600 - x) * e, y * e)
        fun aGauche(x: Int, y: Int) = PointF(x * e, y * e)
        val nuances = Preferences.reperesNuances(service) ?: listOf(
            aDroite(1362, 387), aDroite(1506, 202), aDroite(1465, 272), aDroite(1526, 272), aDroite(1439, 345), aDroite(1542, 643),
        )
        val outils = Preferences.reperesOutils(service) ?: listOf(aGauche(150, 235), aGauche(151, 297), aGauche(409, 158))
        val vue = ReperesNuancesView(contexte, nuances + outils, Array(nuances.size + outils.size) { "${it + 1}" })
        fenetres.addView(vue, params(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT))
        reperesNuances = vue

        val commandes = gonfleur.inflate(R.layout.overlay_reperes, null)
        commandes.findViewById<TextView>(R.id.reperesAide).apply {
            setText(R.string.reperes_nuances_aide)
            maxLines = 6
        }
        commandes.findViewById<View>(R.id.btnAnnuler).setOnClickListener {
            fermerReperes()
            ouvrirPanneau()
        }
        commandes.findViewById<View>(R.id.btnOk).setOnClickListener {
            Preferences.definirReperesNuances(service, vue.points.subList(0, nuances.size))
            Preferences.definirReperesOutils(service, vue.points.subList(nuances.size, vue.points.size))
            if (pour == Pour.NUANCES) Preferences.definirNuancesVoulues(service, true)
            if (pour == Pour.POT) Preferences.definirPotVoulu(service, true)
            SpikeLog.log("Repères des nuances et des outils · écran ${ecran.x}×${ecran.y} · " + vue.points.joinToString(" ") { "(${it.x.toInt()},${it.y.toInt()})" })
            fermerReperes()
            message = ""
            onglet = Onglet.DESSIN
            ouvrirPanneau()
        }
        commandes.measure(
            View.MeasureSpec.makeMeasureSpec(ecran.x - px(16), View.MeasureSpec.AT_MOST),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        )
        val q = params(commandes.measuredWidth, WindowManager.LayoutParams.WRAP_CONTENT).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = px(10)
        }
        fenetres.addView(commandes, q)
        barre = commandes
        etatBulle(Etat.OUVERT)
    }

    private fun fermerReperes() {
        if (reperes == null && reperesNuances == null) return
        retirer(barre); barre = null
        retirer(reperes); reperes = null
        retirer(reperesNuances); reperesNuances = null
    }

    /**
     * Peint l'image choisie dans l'appli : [Peintre] choisit les couleurs, trace, relit la toile après chaque
     * couleur et retouche. [reprendre] : repart des cases déjà peintes si ce dessin a été interrompu.
     */
    private fun lancerDessin(reprendre: Boolean) {
        if (jeu != Jeu.RIEN) return
        val t = Dessin.charger(service) ?: return
        val r = Preferences.reperesDessin(service, t.format)
        if (r == null) {
            ouvrirReperes(t)
            return
        }
        val voit = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R
        val nuances = Preferences.reperesNuances(service)
        val outils = Preferences.reperesOutils(service)
        val avecNuances = voit && nuances != null && Preferences.nuancesVoulues(service)
        val avecPot = voit && outils != null && Preferences.potVoulu(service)
        message = ""

        // La bulle ne doit recouvrir ni la toile, ni la palette, ni les nuances, ni les outils.
        val eviter = ArrayList<PointF>()
        for (k in Dessin.PALETTE.indices) eviter.add(Dessin.pastille(r[2], r[3], k))
        for (i in 0..8) for (j in 0..8) eviter.add(PointF(r[0].x + (r[1].x - r[0].x) * i / 8, r[0].y + (r[1].y - r[0].y) * j / 8))
        if (nuances != null) {
            eviter.addAll(nuances)
            for (rang in 0 until Nuancier.COLONNES * Nuancier.LIGNES) {
                eviter.add(Dessin.nuance(nuances[Etapes.PREMIERE], nuances[Etapes.DERNIERE], rang))
            }
        }
        if (outils != null) eviter.addAll(outils)
        fermerPanneau()
        ecarterBulle(eviter)
        etatBulle(Etat.LECTURE)
        ouvrirCarte(texte(R.string.dessin_carte, t.format, t.couleurs(avecNuances)), texte(R.string.dessin_en_cours), texte(R.string.carte_pause))
        carte?.findViewById<ImageView>(R.id.carteIcone)?.setImageResource(R.drawable.ic_pinceau)
        vuePetiteCarte()
        jeu = Jeu.DESSIN
        // Nos fenêtres apparaissent sur les captures : ce qu'elles cachent de la toile n'est pas relu.
        val masques = listOfNotNull(carte, bulle).mapNotNull { fenetre ->
            (fenetre.layoutParams as? WindowManager.LayoutParams)?.let { android.graphics.Rect(it.x, it.y, it.x + it.width, it.y + it.height) }
        }
        service.peintre.demarrer(
            t, avecNuances, avecPot, prefs.getInt(CASE_MS, CASE_MS_DEFAUT),
            Peintre.Reperes(r[0], r[1], r[2], r[3], nuances, outils, masques), reprendre, ::finDessin,
        )
        principal.post(battement)
    }

    private fun finDessin(bilan: Peintre.Bilan) {
        if (jeu != Jeu.DESSIN) return
        jeu = Jeu.RIEN
        fermerCarte()
        message = when {
            bilan.erreur != 0 -> texte(bilan.erreur)
            bilan.retouchees > 0 || bilan.manquantes > 0 -> texte(R.string.dessin_fini_detail, bilan.retouchees, bilan.manquantes)
            else -> texte(R.string.dessin_fini)
        }
        onglet = Onglet.DESSIN
        reouvrirPanneau()
    }

    /** Pendant le dessin, la carte ne doit pas cacher la toile : elle se réduit à sa première ligne, dans un coin. */
    private fun vuePetiteCarte() {
        val vue = carte ?: return
        vue.findViewById<View>(R.id.carteMeta).visibility = View.GONE
        val p = vue.layoutParams as WindowManager.LayoutParams
        vue.measure(
            View.MeasureSpec.makeMeasureSpec(p.width, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        )
        p.height = vue.measuredHeight
        p.alpha = 0.85f
        if (vue.isAttachedToWindow) fenetres.updateViewLayout(vue, p)
    }

    // ------------------------------------------------------------------ salon

    /**
     * Départ synchronisé demandé par le salon : la première note part dans [delaiMs].
     * Faux si la bulle est éteinte, occupée, ou si le clavier n'est pas calibré pour cet écran.
     */
    fun jouerSalon(titre: String, code: String, arrangement: Arrangement, delaiMs: Long): Boolean {
        if (bulle == null || jeu != Jeu.RIEN) return false
        val touches = Preferences.touches(service, Preferences.disposition(service)) ?: return false
        fermerCalibrage()
        fermerPanneau()
        ecarterBulle(touches)
        etatBulle(Etat.LECTURE)
        dureeLecture = arrangement.dureeMs
        departSalon = SystemClock.uptimeMillis() + delaiMs
        ouvrirCarte(texte(R.string.salon_carte, code), titre, texte(R.string.carte_stop))
        majCarte(0, dureeLecture)
        jeu = Jeu.SALON
        service.lecteur.jouer(
            arrangement.frappes, touches, 1f, 0, prefs.getInt(APPUI, APPUI_DEFAUT).toLong(), delaiMs,
        ) {
            if (jeu == Jeu.SALON) {
                jeu = Jeu.RIEN
                fermerCarte()
                etatBulle(Etat.FERME)
                Salon.finLecture(true)
            }
        }
        principal.post(battement)
        return true
    }

    /** Le salon s'arrête pour tout le monde (chef, annulation, morceau fini côté serveur). */
    fun arreterSalon() {
        if (jeu != Jeu.SALON) return
        service.lecteur.arreter()
        jeu = Jeu.RIEN
        fermerCarte()
        etatBulle(Etat.FERME)
    }

    /** Quatre fois par seconde pendant qu'on joue : avance la carte, ou la pastille allumée du test. */
    private val battement = object : Runnable {
        override fun run() {
            when (jeu) {
                Jeu.MORCEAU -> majCarte(service.lecteur.positionMs(), dureeLecture)
                Jeu.SALON -> {
                    val reste = departSalon - SystemClock.uptimeMillis()
                    if (reste > 0) {
                        carte?.findViewById<TextView>(R.id.carteCompte)?.text = texte(R.string.salon_depart, (reste + 999) / 1000)
                    } else {
                        majCarte(service.lecteur.positionMs(), dureeLecture)
                    }
                }
                Jeu.DESSIN -> {
                    val peintre = service.peintre
                    val fait = peintre.avancement()
                    carte?.findViewById<TextView>(R.id.carteCompte)?.text = "${100 * fait / peintre.total} %"
                    carte?.findViewById<ProgressBar>(R.id.carteBarre)?.progress = (1000L * fait / peintre.total).toInt()
                    carte?.findViewById<TextView>(R.id.carteTemps)?.text = "$fait / ${peintre.total}"
                    val etat = peintre.etat
                    if (etat != null) {
                        carte?.findViewById<TextView>(R.id.carteTitre)?.text = when (etat.phase) {
                            Etapes.Phase.VERIFICATION -> texte(R.string.dessin_verification)
                            Etapes.Phase.RETOUCHES -> texte(R.string.dessin_retouches, etat.detail)
                            Etapes.Phase.REMPLISSAGE -> texte(R.string.dessin_remplissage, etat.detail)
                            Etapes.Phase.PEINTURE ->
                                if (etat.rang > 0) texte(R.string.dessin_couleur, etat.rang, etat.couleurs) else texte(R.string.dessin_en_cours)
                        }
                    }
                }
                Jeu.TEST_TOUCHES -> calibrage?.active = (service.lecteur.positionMs() / PAS_TEST_MS).toInt()
                else -> return
            }
            principal.postDelayed(this, 250)
        }
    }

    /** Carte « en lecture ». Non tactile, pour ne pas avaler les appuis envoyés au jeu. */
    private fun ouvrirCarte(role: String, titre: String, meta: String) {
        fermerCarte()
        val vue = gonfleur.inflate(R.layout.overlay_carte, null)
        vue.findViewById<TextView>(R.id.carteRole).text = role
        vue.findViewById<TextView>(R.id.carteTitre).text = titre
        vue.findViewById<TextView>(R.id.carteMeta).text = meta
        vue.findViewById<ProgressBar>(R.id.carteBarre).max = 1000
        val ecran = tailleEcran(service)
        val largeur = min(px(LARGEUR_MENU_DP), ecran.x - px(16))
        vue.measure(
            View.MeasureSpec.makeMeasureSpec(largeur, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        )
        val p = params(largeur, vue.measuredHeight, WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE)
        placerPresDeLaBulle(p, px(18))
        fenetres.addView(vue, p)
        vue.alpha = 0f
        vue.translationY = -px(12).toFloat()
        vue.animate().alpha(1f).translationY(0f).setDuration(200).start()
        carte = vue
        majCarte(0, 1)
    }

    private fun majCarte(position: Long, duree: Long) {
        val vue = carte ?: return
        val p = position.coerceIn(0, duree)
        vue.findViewById<TextView>(R.id.carteCompte).text = "${100 * p / duree.coerceAtLeast(1)} %"
        vue.findViewById<ProgressBar>(R.id.carteBarre).progress = (1000 * p / duree.coerceAtLeast(1)).toInt()
        vue.findViewById<TextView>(R.id.carteTemps).text = minutes(p) + " / " + minutes(duree)
    }

    private fun fermerCarte() {
        retirer(carte)
        carte = null
    }

    // ------------------------------------------------------------------ calibrage

    private fun ouvrirCalibrage() {
        fermerPanneau()
        if (calibrage != null || bulle == null) return
        val d = Preferences.disposition(service)
        val ecran = tailleEcran(service)
        val inverse = Preferences.inverse(service, d)
        val connues = Preferences.touches(service, d)
        val points = connues ?: CalibrageView.grilleParDefaut(d, ecran.x, ecran.y, inverse)
        val vue = CalibrageView(contexte, points, d, contexte.resources.getStringArray(R.array.noms_notes), inverse)
        if (connues == null) vue.repartirTout()
        fenetres.addView(vue, params(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT))
        calibrage = vue

        val commandes = gonfleur.inflate(R.layout.overlay_calibrage, null)
        commandes.findViewById<View>(R.id.btnInverser).setOnClickListener { vue.inverser() }
        commandes.findViewById<View>(R.id.btnTester).setOnClickListener { testerTouches() }
        commandes.findViewById<View>(R.id.btnAnnuler).setOnClickListener {
            fermerCalibrage()
            ouvrirPanneau()
        }
        commandes.findViewById<View>(R.id.btnOk).setOnClickListener {
            Preferences.definirTouches(service, d, vue.points, vue.inverse)
            SpikeLog.log(
                "Calibrage ${d.id} · écran ${ecran.x}×${ecran.y} · " +
                    vue.points.joinToString(" ") { "(${it.x.toInt()},${it.y.toInt()})" }
            )
            fermerCalibrage()
            message = ""
            onglet = Onglet.MUSIQUE
            ouvrirPanneau()
        }
        // Largeur mesurée à la main : une fenêtre WRAP_CONTENT est d'abord bridée à 320 dp par Android.
        commandes.measure(
            View.MeasureSpec.makeMeasureSpec(ecran.x - px(16), View.MeasureSpec.AT_MOST),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        )
        // En haut au centre : les touches de l'instrument sont en bas de l'écran.
        val q = params(commandes.measuredWidth, WindowManager.LayoutParams.WRAP_CONTENT).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = px(10)
        }
        fenetres.addView(commandes, q)
        barre = commandes
        etatBulle(Etat.OUVERT)
    }

    private fun fermerCalibrage() {
        if (jeu == Jeu.TEST_TOUCHES) {
            service.lecteur.arreter()
            jeu = Jeu.RIEN
        }
        retirer(barre); barre = null
        retirer(calibrage); calibrage = null
    }

    /**
     * Joue chaque touche de la plus grave à la plus aiguë, pastille allumée à l'appui : si la gamme
     * monte dans le jeu, le calibrage est bon. Nos fenêtres laissent passer les appuis le temps du test.
     */
    private fun testerTouches() {
        val vue = calibrage ?: return
        if (jeu != Jeu.RIEN) return
        val touches = vue.points.map { PointF(it.x, it.y) }
        ecarterBulle(touches)
        tactile(vue, false)
        tactile(barre, false)
        etatBulle(Etat.LECTURE)
        jeu = Jeu.TEST_TOUCHES
        service.lecteur.jouer(
            touches.indices.map { Frappe(it * PAS_TEST_MS, intArrayOf(it)) }, touches, 1f, 0,
            prefs.getInt(APPUI, APPUI_DEFAUT).toLong(), 600,
        ) { if (jeu == Jeu.TEST_TOUCHES) finTestTouches() }
        principal.post(battement)
    }

    private fun finTestTouches() {
        jeu = Jeu.RIEN
        calibrage?.active = -1
        tactile(calibrage, true)
        tactile(barre, true)
        etatBulle(Etat.OUVERT)
    }

    // ------------------------------------------------------------------ outils de diagnostic

    /** Test de latence : 32 appuis à 180 bpm sur les touches calibrées, verdict dans l'onglet Outils. */
    private fun lancerLatence() {
        if (jeu != Jeu.RIEN) return
        val touches = Preferences.touches(service, Preferences.disposition(service))
        if (touches == null) {
            ouvrirCalibrage()
            return
        }
        val reglages = Reglages(
            bpm = 180, appuis = 32, accord = false,
            dureeMs = prefs.getInt(APPUI, APPUI_DEFAUT).toLong().coerceAtMost(60000L / 180 - 20),
            reperes = touches,
        )
        fermerPanneau()
        ecarterBulle(touches)
        etatBulle(Etat.LECTURE)
        ouvrirCarte(texte(R.string.latence_role), texte(R.string.latence), texte(R.string.carte_stop))
        jeu = Jeu.LATENCE
        service.metronome.lancer(reglages, { envoyes -> majCarte(envoyes * 333L, reglages.appuis * 333L) }, ::finLatence)
    }

    private fun finLatence(resume: String) {
        if (bulle == null) return
        jeu = Jeu.RIEN
        fermerCarte()
        Resultats.metronome.value = resume
        resumeOutils = resume
        onglet = Onglet.OUTILS
        reouvrirPanneau()
    }

    private fun capturer() {
        fermerPanneau()
        // Le temps que le menu disparaisse de l'écran, sinon c'est lui qu'on photographie.
        principal.postDelayed({
            service.capturer { resume ->
                if (bulle != null) {
                    resumeOutils = resume
                    onglet = Onglet.OUTILS
                    reouvrirPanneau()
                }
            }
        }, 400)
    }

    companion object {
        /** Cercle de 66 dp plus 10 dp de marge de chaque côté (ombre, pastille, anneau). */
        private const val TAILLE_BULLE_DP = 86
        private const val LARGEUR_MENU_DP = 330
        private const val HAUTEUR_LIGNE_DP = 40

        private const val VITESSE = "vitesse"
        private const val APPUI = "appui_ms"
        private const val APPUI_DEFAUT = 40

        /** Dessin : durée ajoutée par case traversée (réglable). Les autres durées sont dans [Peintre]. */
        private const val CASE_MS = "dessin_case_ms"
        private const val CASE_MS_DEFAUT = 18

        /** Laisse le menu se replier avant la première note. */
        private const val DELAI_DEPART_MS = 1500L
        private const val RECUL_REPRISE_MS = 1000L
        private const val PAS_TEST_MS = 350L
    }
}
