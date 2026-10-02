plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "fr.cyberdodo.dodotopia"
    compileSdk = 35

    defaultConfig {
        applicationId = "fr.cyberdodo.dodotopia"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-etape1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Étape 1 : l'APK release part avec la clé debug, le temps des mesures.
            // La vraie clé arrive avec la distribution (étape 2), sinon les mises à jour casseraient.
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-livedata-ktx:2.8.7")
}
