# Schemat procedury lotu i blokad bezpieczeństwa

```text
1. Standby
   └── Otwarcie Oxidizer Intake Valve -> tankowanie utleniacza do 100% -> zamknięcie zaworu
2. Oxidizer Loaded
   └── Otwarcie Fuel Intake Valve -> tankowanie paliwa do 100% -> zamknięcie zaworu
3. Fuel Loaded / Heating Oxidizer Tank
   └── Włączenie Oxidizer Tank Heater -> grzanie do ciśnienia 55–65 bar -> wyłączenie grzałki
4. Ready for Launch (Blokada bezpieczeństwa odblokowana)
   └── Sekwencja zapłonu (< 1 s):
       1) Otwarcie Main Fuel Valve i Main Oxidizer Valve
       2) Odczekanie 0.25 s
       3) Włączenie Engine Igniter na 1.5 s
5. Powered Ascent -> Coasting to Apogee
   └── Spalanie paliwa i wznoszenie do osiągnięcia szczytu pułapu (Apogee Reached)
6. Apogee Reached -> Parachute Descent
   └── Wykrycie początku opadania po apogeum (prędkość <= 0 m/s) -> otwarcie Recovery Parachute
7. Landed
   └── Bezpieczne przyziemienie (wysokość 0.0 m, prędkość 0.0 m/s) -> zakończenie pracy autopilota
```

## Uruchomienie w trzech osobnych terminalach
```bash
python tcp_proxy.py
python tcp_simulator.py
python frontend.py
```
Panel dostępny w przeglądarce: `http://127.0.0.1:8080`
