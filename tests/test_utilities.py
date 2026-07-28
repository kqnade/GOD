from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from god_bot.utilities import (
    CalculationError,
    HELP_TEXT,
    calculate,
    choose_option,
    convert_unit,
    current_weather,
    dns_lookup,
    domain_whois,
    generate_password,
    hash_text,
    ip_lookup,
    parse_utility_command,
    pc_status,
    roll_dice,
    text_stats,
    tls_certificate_info,
)


class UtilityCommandTests(unittest.TestCase):
    def test_parses_weather_and_calc_commands(self) -> None:
        weather = parse_utility_command("天気　東京")
        calc = parse_utility_command("CALC (2 + 3) * 4")
        ping = parse_utility_command("PING")
        whois = parse_utility_command("whois example.com")
        ip = parse_utility_command("ip 8.8.8.8")
        roll = parse_utility_command("roll 2d6")
        choice = parse_utility_command("choice 赤 青")
        dns = parse_utility_command("dns example.com")
        fortune = parse_utility_command("おみくじ")
        association = parse_utility_command("連想 猫")
        summary = parse_utility_command("要約 今日")
        help_command = parse_utility_command("HELP")
        status = parse_utility_command("status")
        pc = parse_utility_command("pc")
        unit = parse_utility_command("unit 10 km mile")
        hash_command = parse_utility_command("hash sha256 abc")
        lisp = parse_utility_command("lisp (let ((x 2)) (+ x 3))")
        earthquake = parse_utility_command("地震")
        amedas = parse_utility_command("アメダス 静岡県 気温")
        quote = parse_utility_command("名言")
        qr = parse_utility_command("qr https://example.com")
        character_count = parse_utility_command("文字数 猫 です")
        tls = parse_utility_command("tls example.com")
        password = parse_utility_command("password 32")
        trial = parse_utility_command("裁判 猫 犬")
        self.assertIsNotNone(weather)
        self.assertIsNotNone(calc)
        assert weather is not None
        assert calc is not None
        assert ping is not None
        assert whois is not None
        assert ip is not None
        assert roll is not None
        assert choice is not None
        assert dns is not None
        assert fortune is not None
        assert association is not None
        assert summary is not None
        assert help_command is not None
        assert status is not None
        assert pc is not None
        assert unit is not None
        assert hash_command is not None
        assert lisp is not None
        assert earthquake is not None
        assert amedas is not None
        assert quote is not None
        assert qr is not None
        assert character_count is not None
        assert tls is not None
        assert password is not None
        assert trial is not None
        self.assertEqual((weather.name, weather.argument), ("天気", "東京"))
        self.assertEqual((calc.name, calc.argument), ("calc", "(2 + 3) * 4"))
        self.assertEqual((ping.name, ping.argument), ("ping", ""))
        self.assertEqual(
            (whois.name, whois.argument),
            ("whois", "example.com"),
        )
        self.assertEqual((ip.name, ip.argument), ("ip", "8.8.8.8"))
        self.assertEqual((roll.name, roll.argument), ("roll", "2d6"))
        self.assertEqual((choice.name, choice.argument), ("choice", "赤 青"))
        self.assertEqual((dns.name, dns.argument), ("dns", "example.com"))
        self.assertEqual((fortune.name, fortune.argument), ("おみくじ", ""))
        self.assertEqual(
            (association.name, association.argument),
            ("連想", "猫"),
        )
        self.assertEqual((summary.name, summary.argument), ("要約", "今日"))
        self.assertEqual((help_command.name, help_command.argument), ("help", ""))
        self.assertEqual((status.name, status.argument), ("status", ""))
        self.assertEqual((pc.name, pc.argument), ("pc", ""))
        self.assertEqual(
            (unit.name, unit.argument),
            ("unit", "10 km mile"),
        )
        self.assertEqual(
            (hash_command.name, hash_command.argument),
            ("hash", "sha256 abc"),
        )
        self.assertEqual(
            (lisp.name, lisp.argument),
            ("lisp", "(let ((x 2)) (+ x 3))"),
        )
        self.assertEqual(
            (earthquake.name, earthquake.argument),
            ("地震", ""),
        )
        self.assertEqual(
            (amedas.name, amedas.argument),
            ("アメダス", "静岡県 気温"),
        )
        self.assertEqual((quote.name, quote.argument), ("名言", ""))
        self.assertEqual(
            (qr.name, qr.argument),
            ("qr", "https://example.com"),
        )
        self.assertEqual(
            (character_count.name, character_count.argument),
            ("文字数", "猫 です"),
        )
        self.assertEqual((tls.name, tls.argument), ("tls", "example.com"))
        self.assertEqual(
            (password.name, password.argument),
            ("password", "32"),
        )
        self.assertEqual((trial.name, trial.argument), ("裁判", "猫 犬"))

    def test_help_lists_all_utility_commands(self) -> None:
        for command in (
            "ping",
            "status",
            "pc",
            "calc",
            "unit",
            "hash",
            "lisp",
            "地震",
            "アメダス",
            "名言",
            "qr",
            "文字数",
            "tls",
            "password",
            "裁判",
            "roll",
            "choice",
            "天気",
            "dns",
            "whois",
            "ip",
            "おみくじ",
            "連想",
            "要約",
        ):
            self.assertIn(command, HELP_TEXT)
        self.assertLessEqual(len(HELP_TEXT), 1_800)

    def test_does_not_capture_normal_conversation(self) -> None:
        self.assertIsNone(parse_utility_command("今日の天気どう？"))
        self.assertIsNone(parse_utility_command("calcって便利"))

    def test_calculates_basic_and_full_width_expressions(self) -> None:
        self.assertEqual(calculate("(12 + 3) * 4"), "60")
        self.assertEqual(calculate("２＾８"), "256")
        self.assertEqual(calculate("7 ÷ 2"), "3.5")

    def test_rejects_code_and_dangerous_or_huge_expressions(self) -> None:
        with self.assertRaises(CalculationError):
            calculate("__import__('os').getcwd()")
        with self.assertRaises(CalculationError):
            calculate("1 / 0")
        with self.assertRaises(CalculationError):
            calculate("2 ** 1000")

    @patch("god_bot.utilities._get_json")
    def test_weather_falls_back_for_japanese_place_name(
        self, get_json
    ) -> None:
        get_json.side_effect = [
            {},
            [
                {
                    "lat": "35.68",
                    "lon": "139.76",
                    "display_name": "東京都, 日本",
                    "address": {
                        "city": "東京都",
                        "state": "東京都",
                        "country": "日本",
                    },
                }
            ],
            {
                "current": {
                    "weather_code": 1,
                    "temperature_2m": 28.5,
                    "apparent_temperature": 30.2,
                    "relative_humidity_2m": 70,
                    "precipitation": 0,
                    "wind_speed_10m": 8.4,
                }
            },
        ]
        result = current_weather("東京")
        self.assertIn("📍 観測地点: 東京都 / 日本（35.6800, 139.7600）", result)
        self.assertIn("現在: ほぼ晴れ、28.5℃", result)
        self.assertIn("湿度70%", result)

    @patch("god_bot.utilities._get_json")
    def test_fetches_tomorrows_forecast(self, get_json) -> None:
        get_json.side_effect = [
            {
                "results": [
                    {
                        "latitude": 34.71,
                        "longitude": 137.73,
                        "name": "浜松市",
                        "admin1": "静岡県",
                        "country": "日本",
                    }
                ]
            },
            {
                "daily": {
                    "time": ["2026-07-27", "2026-07-28"],
                    "weather_code": [2, 61],
                    "temperature_2m_max": [31.0, 29.5],
                    "temperature_2m_min": [24.0, 23.2],
                    "precipitation_probability_max": [20, 70],
                    "precipitation_sum": [0, 4.2],
                    "wind_speed_10m_max": [12.0, 18.4],
                }
            },
        ]
        result = current_weather("浜松 明日")
        self.assertIn(
            "📍 観測地点: 浜松市 / 静岡県 / 日本（34.7100, 137.7300）",
            result,
        )
        self.assertIn("明日（2026-07-28）", result)
        self.assertIn("弱い雨", result)
        self.assertIn("降水確率70%", result)
        self.assertIn("最高29.5℃・最低23.2℃", result)

    @patch("god_bot.utilities._get_json")
    def test_fetches_next_week_forecast(self, get_json) -> None:
        dates = [f"2026-07-{day:02d}" for day in range(27, 32)]
        dates += [f"2026-08-{day:02d}" for day in range(1, 10)]
        get_json.side_effect = [
            {
                "results": [
                    {
                        "latitude": 34.71,
                        "longitude": 137.73,
                        "name": "浜松市",
                    }
                ]
            },
            {
                "daily": {
                    "time": dates,
                    "weather_code": [1] * 14,
                    "temperature_2m_max": [30] * 14,
                    "temperature_2m_min": [22] * 14,
                    "precipitation_probability_max": [20] * 14,
                    "precipitation_sum": [0] * 14,
                    "wind_speed_10m_max": [10] * 14,
                }
            },
        ]
        result = current_weather("浜松 来週")
        self.assertIn("📍 観測地点: 浜松市（34.7100, 137.7300）", result)
        self.assertIn("来週の予報:", result)
        self.assertIn("8/3（月）", result)
        self.assertIn("8/9（日）", result)
        self.assertNotIn("8/2（日）", result)
        self.assertEqual(len(result.splitlines()), 9)

    @patch("god_bot.utilities._get_json")
    def test_fetches_domain_rdap_information(self, get_json) -> None:
        get_json.return_value = {
            "ldhName": "EXAMPLE.COM",
            "status": ["client delete prohibited"],
            "events": [
                {
                    "eventAction": "registration",
                    "eventDate": "1995-08-14T04:00:00Z",
                },
                {
                    "eventAction": "expiration",
                    "eventDate": "2027-08-13T04:00:00Z",
                },
            ],
            "entities": [
                {
                    "roles": ["registrar"],
                    "vcardArray": [
                        "vcard",
                        [["fn", {}, "text", "Example Registrar"]],
                    ],
                }
            ],
            "nameservers": [
                {"ldhName": "A.IANA-SERVERS.NET"},
                {"ldhName": "B.IANA-SERVERS.NET"},
            ],
        }
        result = domain_whois("https://example.com/path")
        self.assertIn("ドメイン: EXAMPLE.COM", result)
        self.assertIn("レジストラ: Example Registrar", result)
        self.assertIn("登録日: 1995-08-14", result)
        self.assertIn("A.IANA-SERVERS.NET", result)

    def test_rejects_invalid_whois_target(self) -> None:
        self.assertIn(
            "ドメイン名だけ",
            domain_whois("not a domain"),
        )

    @patch("god_bot.utilities._get_json")
    def test_fetches_ip_rdap_information(self, get_json) -> None:
        get_json.return_value = {
            "name": "GOOGLE",
            "type": "DIRECT ALLOCATION",
            "startAddress": "8.8.8.0",
            "endAddress": "8.8.8.255",
            "country": "US",
            "entities": [
                {
                    "roles": ["registrant"],
                    "vcardArray": [
                        "vcard",
                        [["fn", {}, "text", "Google LLC"]],
                    ],
                }
            ],
        }
        result = ip_lookup("8.8.8.8")
        self.assertIn("IP: 8.8.8.8（IPv4）", result)
        self.assertIn("ネットワーク: GOOGLE", result)
        self.assertIn("8.8.8.0 - 8.8.8.255", result)
        self.assertIn("管理組織: Google LLC", result)

    def test_rejects_private_ip_lookup(self) -> None:
        self.assertIn("公開IP", ip_lookup("192.168.1.1"))

    def test_rolls_dice_with_modifier(self) -> None:
        result = roll_dice("2d6+3", rng=random.Random(1))
        self.assertEqual(result, "🎲 2d6+3: [2, 5] → 合計 10")

    def test_rolls_one_die_when_only_sides_are_given(self) -> None:
        result = roll_dice("20", rng=random.Random(1))
        self.assertEqual(result, "🎲 1d20: [5] → 合計 5")

    def test_rolls_d100_when_argument_is_omitted(self) -> None:
        result = roll_dice("", rng=random.Random(1))
        self.assertEqual(result, "🎲 1d100: [18] → 合計 18")

    def test_chooses_from_space_or_comma_separated_options(self) -> None:
        result = choose_option("赤 青 緑", rng=random.Random(2))
        self.assertIn(result, {"これにする: **赤**", "これにする: **青**", "これにする: **緑**"})
        comma_result = choose_option("犬、猫、鳥", rng=random.Random(2))
        self.assertIn("**", comma_result)

    @patch("god_bot.utilities._get_json")
    def test_fetches_dns_records(self, get_json) -> None:
        get_json.side_effect = [
            {"Answer": [{"data": "93.184.216.34"}]},
            {},
            {"Answer": [{"data": "10 mail.example.com."}]},
        ]
        result = dns_lookup("example.com")
        self.assertIn("A: 93.184.216.34", result)
        self.assertIn("MX: 10 mail.example.com", result)

    def test_converts_units_and_temperatures(self) -> None:
        self.assertEqual(
            convert_unit("10 km mile"),
            "10 km = 6.21371192237 mile",
        )
        self.assertEqual(convert_unit("0 C F"), "0 C = 32 F")
        self.assertIn("同じ種類", convert_unit("1 kg km"))

    def test_hashes_text(self) -> None:
        result = hash_text("sha256 abc")
        self.assertIn(
            "ba7816bf8f01cfea414140de5dae2223"
            "b00361a396177a9cb410ff61f20015ad",
            result,
        )
        self.assertIn("安全な署名", hash_text("md5 abc"))

    def test_counts_characters_lines_and_utf8_bytes(self) -> None:
        self.assertEqual(
            text_stats("猫 です\n犬"),
            "文字数: 6\n空白除外: 4\n行数: 2\nUTF-8: 14バイト",
        )
        self.assertIn("例:", text_stats(""))

    def test_generates_password_with_all_character_groups(self) -> None:
        result = generate_password("32")
        password = result.split("`")[1]
        self.assertEqual(len(password), 32)
        self.assertTrue(any(char.islower() for char in password))
        self.assertTrue(any(char.isupper() for char in password))
        self.assertTrue(any(char.isdigit() for char in password))
        self.assertTrue(any(char in "!@#$%^&*()-_=+" for char in password))
        self.assertIn("8〜128", generate_password("7"))
        self.assertIn("例:", generate_password("long"))

    @patch("god_bot.utilities.ssl.create_default_context")
    @patch("god_bot.utilities.socket.create_connection")
    @patch("god_bot.utilities.socket.getaddrinfo")
    def test_reads_tls_certificate(
        self,
        getaddrinfo,
        create_connection,
        create_default_context,
    ) -> None:
        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FakeTls(FakeConnection):
            def getpeercert(self):
                return {
                    "subject": ((("commonName", "example.com"),),),
                    "issuer": (
                        (("organizationName", "Example CA"),),
                    ),
                    "notAfter": "Jan  1 00:00:00 2100 GMT",
                    "subjectAltName": (
                        ("DNS", "example.com"),
                        ("DNS", "www.example.com"),
                    ),
                }

            def version(self):
                return "TLSv1.3"

            def cipher(self):
                return ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)

        getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 443))
        ]
        create_connection.return_value = FakeConnection()
        create_default_context.return_value.wrap_socket.return_value = FakeTls()
        result = tls_certificate_info("example.com")
        self.assertIn("TLS: example.com", result)
        self.assertIn("Example CA", result)
        self.assertIn("2100-01-01", result)
        self.assertIn("DNS名: 2件", result)
        self.assertIn("TLSv1.3 / TLS_AES_256_GCM_SHA384", result)

    @patch("god_bot.utilities.socket.getaddrinfo")
    def test_rejects_tls_domain_resolving_to_private_ip(
        self,
        getaddrinfo,
    ) -> None:
        getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 443))
        ]
        self.assertIn("公開IP", tls_certificate_info("localhost.example"))

    def test_reads_pc_status_from_proc_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            proc_root.mkdir()
            (proc_root / "loadavg").write_text(
                "0.10 0.20 0.30 1/100 123\n",
                encoding="utf-8",
            )
            (proc_root / "uptime").write_text(
                "90061.00 0.00\n",
                encoding="utf-8",
            )
            (proc_root / "meminfo").write_text(
                "MemTotal: 1048576 kB\nMemAvailable: 524288 kB\n",
                encoding="utf-8",
            )
            result = pc_status(proc_root=proc_root, disk_path=root)
        self.assertIn("負荷 0.10, 0.20, 0.30", result)
        self.assertIn("メモリ: 512.0MiB / 1.0GiB（50.0%）", result)
        self.assertIn("1日1時間1分1秒", result)


if __name__ == "__main__":
    unittest.main()
