# Traffic alarms, emailed through bootstrap's alerts topic. A portfolio site sees a few
# hundred requests a day, so either alarm means a crawler, an attack or a very good day.
# Both thresholds sit far below CloudFront's always-free allowance (10 million requests and
# 1 TB a month), so they warn long before anything costs money. Names must start with
# portfolio-production- (the role's alarm permission).

data "aws_sns_topic" "alerts" {
  name = "portfolio-alerts"
}

locals {
  # CloudFront publishes its metrics in us-east-1, under the Global region.
  distribution = {
    DistributionId = module.site.distribution_id
    Region         = "Global"
  }
}

resource "aws_cloudwatch_metric_alarm" "requests" {
  alarm_name          = "portfolio-production-requests"
  alarm_description   = "More than 20,000 requests to ${var.domain} in an hour."
  namespace           = "AWS/CloudFront"
  metric_name         = "Requests"
  dimensions          = local.distribution
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 20000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "bytes" {
  alarm_name          = "portfolio-production-bytes"
  alarm_description   = "More than 10 GB served by ${var.domain} in a day."
  namespace           = "AWS/CloudFront"
  metric_name         = "BytesDownloaded"
  dimensions          = local.distribution
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 10 * 1000 * 1000 * 1000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}
