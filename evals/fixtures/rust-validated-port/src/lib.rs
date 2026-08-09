pub fn parse_port(value: &str) -> Result<u16, String> {
    value
        .parse::<u16>()
        .map_err(|_| "port must be a number from 1 through 65535".to_string())
}

#[cfg(test)]
mod tests {
    use super::parse_port;

    #[test]
    fn accepts_trimmed_valid_ports() {
        assert_eq!(parse_port(" 443 "), Ok(443));
        assert_eq!(parse_port("65535"), Ok(65535));
    }

    #[test]
    fn rejects_zero_and_invalid_values() {
        assert!(parse_port("0").is_err());
        assert!(parse_port("65536").is_err());
        assert!(parse_port("http").is_err());
    }
}
